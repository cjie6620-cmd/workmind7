"""可持久恢复、按用户隔离的内容工作流 API

生命周期：start（受理即写 Redis running 快照）→ 节点流式推送 → 人工审核暂停
（paused 快照可跨 worker / 刷新恢复）→ resume（分布式锁 + 复读快照防 TOCTOU）
→ 终态 completed/failed/cancelled 全部落 Redis（TTL 24h）。
取消写「墓碑」快照，防止迟到的另一 worker 结果把终态改回可见状态；
配置停用只阻止新任务启动，不追溯在途/暂停任务。
"""

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from ..auth.dependencies import get_current_user
from ..auth.models import UserContext
from ..schemas.requests import WorkflowResumeRequest, WorkflowStartRequest
from ..services.config.config_service import list_configs as list_wf_configs
from ..services.workflow.state_store import (
    acquire_workflow_lock,
    get_workflow_run,
    release_workflow_lock,
    save_workflow_run,
)
from ..services.workflow.workflows import WORKFLOW_BUILDERS, WORKFLOW_META
from ..utils.background_tasks import wait_or_cancel_tasks
from ..utils.logger import logger
from ..utils.sse import sse_error, sse_event
from ..utils.sse_disconnect import pump_queue_events
from ..utils.responses import error_response

workflow_router = APIRouter()
_workflow_tasks: dict[str, asyncio.Task] = {}


def _track_workflow_task(thread_id: str, task: asyncio.Task) -> asyncio.Task:
    """保留业务任务的强引用；SSE 连接结束不等同于取消业务执行。"""
    _workflow_tasks[thread_id] = task

    def _forget(completed: asyncio.Task) -> None:
        if _workflow_tasks.get(thread_id) is completed:
            _workflow_tasks.pop(thread_id, None)

    task.add_done_callback(_forget)
    return task


async def shutdown_workflow_tasks(timeout_seconds: float = 20) -> None:
    """优雅停机时等待已受理流程落到 Redis 终态，再取消超时任务。"""
    await wait_or_cancel_tasks(_workflow_tasks.values(), timeout_seconds)


INTERMEDIATES_MAP = {
    "weekly_report": {"highlights": "提炼的亮点", "risks": "风险/阻塞项"},
    "meeting_minutes": {
        "attendees": "参会人与议题",
        "conclusions": "会议结论",
        "action_items": "Action Items",
    },
    "email_polish": {"purpose": "意图分析", "issues": "发现的问题"},
    "prd_skeleton": {"features": "功能点", "constraints": "约束条件"},
}

# 用于在另一个 worker 中重建 interrupt_before('human_review') 的 checkpoint。
PAUSE_PREDECESSOR = {
    "weekly_report": "identify_risks",
    "meeting_minutes": "extract_actions",
    "email_polish": "check_issues",
    "prd_skeleton": "identify_constraints",
}

INPUT_SPECS = {
    "weekly_report": ("points", ("points",), "dept", ("dept",)),
    "meeting_minutes": ("raw_notes", ("raw_notes", "rawNotes"), "meeting_title", ("meeting_title", "meetingTitle")),
    "email_polish": ("draft", ("draft",), "recipient", ("recipient",)),
    "prd_skeleton": ("description", ("description",), None, ()),
}


def _get_intermediates(values: dict, workflow_id: str) -> list[dict]:
    """从图状态提取该工作流的中间产物（人工审核面板展示用）。"""
    field_map = INTERMEDIATES_MAP.get(workflow_id, {})
    return [
        {"key": key, "label": label, "value": values.get(key)} for key, label in field_map.items() if values.get(key)
    ]


def _normalize_input(workflow_id: str, raw_input: dict) -> dict:
    """统一前后端别名并对每种工作流执行必填和长度校验。"""
    spec = INPUT_SPECS.get(workflow_id)
    if not spec:
        raise ValueError(f"未知工作流：{workflow_id}")
    main_key, main_aliases, extra_key, extra_aliases = spec

    main_value = next((raw_input.get(key) for key in main_aliases if raw_input.get(key) is not None), None)
    if not isinstance(main_value, str) or not main_value.strip():
        raise ValueError("工作流输入内容不能为空")
    if len(main_value) > 12_000:
        raise ValueError("工作流输入内容不能超过 12000 字")

    normalized = {main_key: main_value.strip()}
    if extra_key:
        extra_value = next((raw_input.get(key) for key in extra_aliases if raw_input.get(key) is not None), "")
        if extra_value is not None and not isinstance(extra_value, str):
            raise ValueError("附加字段必须是文本")
        if len(extra_value or "") > 200:
            raise ValueError("附加字段不能超过 200 字")
        normalized[extra_key] = (extra_value or "").strip()
    return normalized


async def _active_templates() -> list[dict] | None:
    """配置中心只控制已注册内置实现的展示与启停，避免展示不可运行模板。"""
    configs = await list_wf_configs("workflow")
    if not configs:
        return None
    templates = []
    for config in configs:
        workflow_id = config["name"]
        if not config.get("isActive") or workflow_id not in WORKFLOW_BUILDERS:
            continue
        config_json = config["configJson"]
        built_in = WORKFLOW_META[workflow_id]
        templates.append(
            {
                "id": workflow_id,
                "title": config_json.get("title", built_in["title"]),
                "icon": config_json.get("icon", built_in["icon"]),
                "desc": config_json.get("description", built_in["desc"]),
                "inputLabel": config_json.get("inputLabel", built_in["inputLabel"]),
                "inputPlaceholder": config_json.get("inputPlaceholder", built_in["inputPlaceholder"]),
                "extraField": config_json.get("extraField", built_in.get("extraField")),
                # 运行节点来自受版本控制的实现，不能由任意 JSON 伪造。
                "nodes": built_in["nodes"],
                "resultKey": built_in["resultKey"],
            }
        )
    return templates


async def _workflow_is_active(workflow_id: str) -> bool:
    """判断工作流是否允许启动新任务；无任何配置时回退为内置全启用。"""
    configs = await list_wf_configs("workflow")
    if not configs:
        return workflow_id in WORKFLOW_BUILDERS
    return any(item["name"] == workflow_id and item.get("isActive") for item in configs)


def _public_run(run: dict) -> dict:
    """把 Redis 快照裁剪为公开契约（不泄露 values/userId 等内部字段）。"""
    public = {
        "threadId": run["threadId"],
        "workflowId": run["workflowId"],
        "status": run["status"],
        "intermediates": run.get("intermediates", []),
        "updatedAt": run.get("updatedAt"),
    }
    if run.get("result") is not None:
        public["result"] = run["result"]
    if run.get("error"):
        public["error"] = run["error"]
    return public


@workflow_router.get("/templates")
async def get_templates():
    """返回可启动的工作流模板；配置中心不可用时降级为内置默认列表。"""
    try:
        templates = await _active_templates()
        # 仅在尚未创建任何配置时展示内置默认值；若配置全部停用，必须返回空列表。
        return {
            "templates": list(WORKFLOW_META.values()) if templates is None else templates,
        }
    except Exception as err:
        logger.warning("workflow: config lookup failed", {"error": str(err)})
        return {"templates": list(WORKFLOW_META.values())}


@workflow_router.get("/runs/{thread_id}")
async def get_run(
    thread_id: str,
    user: UserContext = Depends(get_current_user),
):
    """查询运行快照（断线重连/刷新后恢复用）；非本人一律 404 防枚举。"""
    run = await get_workflow_run(thread_id)
    if not run or run.get("userId") != user.user_id:
        return error_response(404, "工作流不存在或已过期")
    return {"run": _public_run(run)}


@workflow_router.delete("/runs/{thread_id}")
async def cancel_run(
    thread_id: str,
    user: UserContext = Depends(get_current_user),
):
    """显式取消工作流：取分布式锁 → 复读快照 → 写取消墓碑 → 取消本地任务。"""
    run = await get_workflow_run(thread_id)
    if not run or run.get("userId") != user.user_id:
        return error_response(404, "工作流不存在或已过期")
    lock_token = await acquire_workflow_lock(thread_id)
    if not lock_token:
        return error_response(409, "工作流正在恢复，暂时无法取消")
    try:
        # 取锁后复读，用最新快照写墓碑；对已终态运行幂等返回，避免把 completed 改写成 cancelled。
        run = await get_workflow_run(thread_id)
        if not run or run.get("userId") != user.user_id:
            return error_response(404, "工作流不存在或已过期")
        if run.get("status") in {"completed", "failed", "cancelled"}:
            return {"success": True, "status": run.get("status")}
        # 保留取消墓碑到 TTL，防止另一个 worker 的迟到结果重新写回可见状态。
        await save_workflow_run(thread_id, {**run, "status": "cancelled"})
        task = _workflow_tasks.get(thread_id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    finally:
        try:
            await release_workflow_lock(thread_id, lock_token)
        except Exception as lock_err:
            logger.error(
                "workflow: cancel lock release failed",
                {
                    "threadId": thread_id,
                    "error": str(lock_err),
                },
            )
    return {"success": True}


@workflow_router.post("/start/stream")
async def start_workflow_stream(
    req: WorkflowStartRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """启动工作流：校验入参 → 落 running 快照 → 后台跑图 → SSE 推送节点事件。

    事件契约：start → node_start/node_done/token* →（paused | completed）；
    异常推 error。受理后断连只停推送，任务继续执行并落终态。
    """
    workflow_id = req.workflowId
    if workflow_id not in WORKFLOW_BUILDERS:
        return error_response(400, f"未知工作流：{workflow_id}")
    if not await _workflow_is_active(workflow_id):
        return error_response(409, "该工作流已停用")
    try:
        input_data = _normalize_input(workflow_id, req.input)
    except ValueError as err:
        return error_response(422, str(err))

    thread_id = f"wf_{user.user_id}_{uuid.uuid4().hex}"
    graph_config = {"configurable": {"thread_id": thread_id}}
    queue: asyncio.Queue = asyncio.Queue()
    done_event = asyncio.Event()
    terminal = {"status": None}
    transport = {"connected": True}
    initial_run = {
        "workflowId": workflow_id,
        "userId": user.user_id,
        "status": "running",
        "values": input_data,
        "intermediates": [],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await save_workflow_run(thread_id, initial_run)
    except Exception as err:
        logger.error(
            "workflow: initial state persistence failed",
            {
                "threadId": thread_id,
                "error": str(err),
            },
        )
        return error_response(503, "工作流状态存储暂不可用，请稍后重试")

    async def emit(item) -> None:
        if transport["connected"]:
            await queue.put(item)

    async def run():
        try:
            graph = WORKFLOW_BUILDERS[workflow_id]()
            meta = WORKFLOW_META[workflow_id]
            last_node = None

            async for event in graph.astream_events(input_data, config=graph_config, version="v2"):
                event_type = event["event"]
                name = event.get("name", "")
                data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}

                if event_type == "on_chain_start" and name not in ("__start__", "LangGraph"):
                    node_meta = next((node for node in meta["nodes"] if node["id"] == name), None)
                    if node_meta and name != last_node:
                        last_node = name
                        await emit(sse_event("node_start", {"nodeId": name, "label": node_meta["label"]}))

                if event_type == "on_chain_end" and name not in ("__end__", "LangGraph"):
                    node_meta = next((node for node in meta["nodes"] if node["id"] == name), None)
                    if node_meta:
                        output = data.get("output", {})
                        preview = ""
                        if isinstance(output, dict):
                            first_value = next(iter(output.values()), "")
                            if isinstance(first_value, str) and first_value:
                                preview = first_value[:80] + ("..." if len(first_value) > 80 else "")
                        await emit(sse_event("node_done", {"nodeId": name, "preview": preview}))

            state = graph.get_state(graph_config)
            current_run = await get_workflow_run(thread_id)
            if not current_run or current_run.get("status") == "cancelled":
                terminal["status"] = "cancelled"
                return
            if state.next:
                intermediates = _get_intermediates(state.values, workflow_id)
                await save_workflow_run(
                    thread_id,
                    {
                        "workflowId": workflow_id,
                        "userId": user.user_id,
                        "status": "paused",
                        "values": dict(state.values),
                        "intermediates": intermediates,
                        "createdAt": datetime.now(timezone.utc).isoformat(),
                    },
                )
                terminal["status"] = "paused"
                await emit(
                    sse_event(
                        "paused",
                        {
                            "threadId": thread_id,
                            "nextNode": state.next[0],
                            "intermediates": intermediates,
                        },
                    )
                )
            else:
                terminal["status"] = "completed"
                result = state.values.get(meta["resultKey"], "")
                await save_workflow_run(
                    thread_id,
                    {
                        **initial_run,
                        "status": "completed",
                        "values": dict(state.values),
                        "result": result,
                    },
                )
                await emit(sse_event("completed", {"threadId": thread_id, "result": result}))
        except asyncio.CancelledError:
            terminal["status"] = "cancelled"
            # 停机等场景的取消：若不是用户已写的 cancelled 墓碑，落一个终态，避免 Redis 记录永远停在 running
            try:
                current_run = await get_workflow_run(thread_id)
                if current_run and current_run.get("status") == "running":
                    await save_workflow_run(
                        thread_id,
                        {**current_run, "status": "failed", "error": "服务重启导致任务中断，请重试"},
                    )
            except Exception as persist_err:
                logger.error(
                    "workflow: cancel terminal persistence failed",
                    {"threadId": thread_id, "error": str(persist_err)},
                )
            raise
        except Exception as err:
            terminal["status"] = "failed"
            logger.error("workflow: start error", {"error": str(err), "threadId": thread_id})
            try:
                current_run = await get_workflow_run(thread_id)
                if current_run and current_run.get("status") != "cancelled":
                    await save_workflow_run(
                        thread_id,
                        {
                            **current_run,
                            "status": "failed",
                            "error": "工作流执行失败，请重试",
                        },
                    )
            except Exception as persistence_err:
                logger.error(
                    "workflow: failed state persistence failed",
                    {
                        "threadId": thread_id,
                        "error": str(persistence_err),
                    },
                )
            await emit(sse_error(err))
        finally:
            done_event.set()

    _track_workflow_task(
        thread_id,
        asyncio.create_task(run(), name=f"workflow-start-{thread_id}"),
    )

    async def event_generator():
        yield sse_event("start", {"threadId": thread_id, "workflowId": workflow_id})
        try:
            async for item in pump_queue_events(request, queue, done_event):
                yield item
        finally:
            transport["connected"] = False
        if not await request.is_disconnected() and terminal["status"] not in {"failed", "cancelled"}:
            yield sse_event("done", {"threadId": thread_id, "status": terminal["status"]})

    return EventSourceResponse(event_generator())


@workflow_router.post("/resume/stream")
async def resume_workflow_stream(
    req: WorkflowResumeRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """人工审核后恢复暂停的工作流（可跨 worker：按快照重建 checkpoint 续跑）。

    并发防护：分布式锁保证同一 thread 只有一个恢复执行者；
    取锁后复读快照（TOCTOU），写终态前再复读（不覆盖取消墓碑）。
    """
    thread_id = req.threadId
    snapshot = await get_workflow_run(thread_id)
    if not snapshot or snapshot.get("userId") != user.user_id:
        return error_response(404, "工作流不存在或已过期，请重新启动")

    if snapshot.get("status") != "paused":
        return error_response(409, "工作流当前不处于待审核状态")

    workflow_id = snapshot.get("workflowId")
    if workflow_id not in WORKFLOW_BUILDERS or workflow_id not in PAUSE_PREDECESSOR:
        return error_response(409, "工作流版本已失效，请重新启动")

    lock_token = await acquire_workflow_lock(thread_id)
    if not lock_token:
        return error_response(409, "工作流正在恢复，请勿重复提交")

    # TOCTOU：加锁前的 paused 快照可能已被并发 cancel/resume 改写。取锁后必须复读，
    # 状态不再是 paused（或归属变化）则释放锁并拒绝，避免用陈旧快照重复执行/复活已取消任务。
    snapshot = await get_workflow_run(thread_id)
    if not snapshot or snapshot.get("userId") != user.user_id:
        await release_workflow_lock(thread_id, lock_token)
        return error_response(404, "工作流不存在或已过期，请重新启动")
    if snapshot.get("status") != "paused":
        await release_workflow_lock(thread_id, lock_token)
        return error_response(409, "工作流当前不处于待审核状态")

    meta = WORKFLOW_META[workflow_id]
    graph_config = {"configurable": {"thread_id": thread_id}}
    queue: asyncio.Queue = asyncio.Queue()
    done_event = asyncio.Event()
    terminal = {"status": None}
    transport = {"connected": True}

    async def emit(item) -> None:
        if transport["connected"]:
            await queue.put(item)

    async def run():
        try:
            graph = WORKFLOW_BUILDERS[workflow_id]()
            # 在当前 worker 的新 checkpointer 中还原暂停点。
            graph.update_state(
                graph_config,
                snapshot["values"],
                as_node=PAUSE_PREDECESSOR[workflow_id],
            )
            if req.feedback.strip():
                graph.update_state(graph_config, {"human_feedback": req.feedback.strip()})

            last_node = None
            async for event in graph.astream_events(None, config=graph_config, version="v2"):
                event_type = event["event"]
                name = event.get("name", "")
                data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}

                if event_type == "on_chain_start" and name not in ("__start__", "__end__", "LangGraph"):
                    node_meta = next((node for node in meta["nodes"] if node["id"] == name), None)
                    if node_meta and name != last_node:
                        last_node = name
                        await emit(sse_event("node_start", {"nodeId": name, "label": node_meta["label"]}))
                if event_type == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if chunk and chunk.content:
                        await emit(sse_event("token", {"token": chunk.content}))
                if event_type == "on_chain_end":
                    node_meta = next((node for node in meta["nodes"] if node["id"] == name), None)
                    if node_meta:
                        await emit(sse_event("node_done", {"nodeId": name}))

            # 写终态前复读：若期间被取消（如锁 TTL 过期后 cancel 写入墓碑），不覆盖取消状态。
            current_run = await get_workflow_run(thread_id)
            if not current_run or current_run.get("status") == "cancelled":
                terminal["status"] = "cancelled"
                return

            final_state = graph.get_state(graph_config)
            if final_state.next:
                # 当前内置流程只有一个人工节点；仍保留通用的再次暂停语义。
                intermediates = _get_intermediates(final_state.values, workflow_id)
                snapshot["values"] = dict(final_state.values)
                snapshot["intermediates"] = intermediates
                snapshot["status"] = "paused"
                await save_workflow_run(thread_id, snapshot)
                terminal["status"] = "paused"
                await emit(
                    sse_event(
                        "paused",
                        {
                            "threadId": thread_id,
                            "nextNode": final_state.next[0],
                            "intermediates": intermediates,
                        },
                    )
                )
            else:
                result = final_state.values.get(meta["resultKey"], "")
                snapshot["values"] = dict(final_state.values)
                snapshot["intermediates"] = []
                snapshot["status"] = "completed"
                snapshot["result"] = result
                await save_workflow_run(thread_id, snapshot)
                terminal["status"] = "completed"
                await emit(sse_event("completed", {"threadId": thread_id, "result": result}))
                logger.info("workflow: completed", {"threadId": thread_id, "userId": user.user_id})
        except asyncio.CancelledError:
            terminal["status"] = "cancelled"
            raise
        except Exception as err:
            terminal["status"] = "failed"
            logger.error("workflow: resume error", {"error": str(err), "threadId": thread_id})
            try:
                await save_workflow_run(
                    thread_id,
                    {
                        **snapshot,
                        "status": "failed",
                        # 与 start 路径一致：只存通用文案，原始错误细节仅进日志，避免外泄。
                        "error": "工作流执行失败，请重试",
                    },
                )
            except Exception as persist_err:
                logger.error(
                    "workflow: persist resume failure failed",
                    {"threadId": thread_id, "error": str(persist_err)},
                )
            await emit(sse_error(err))
        finally:
            try:
                await release_workflow_lock(thread_id, lock_token)
            except Exception as lock_err:
                # 锁有 TTL；释放失败不应把已经完成的业务结果改判为失败。
                logger.error(
                    "workflow: release lock failed",
                    {
                        "threadId": thread_id,
                        "error": str(lock_err),
                    },
                )
            finally:
                done_event.set()

    _track_workflow_task(
        thread_id,
        asyncio.create_task(run(), name=f"workflow-resume-{thread_id}"),
    )

    async def event_generator():
        yield sse_event("resumed", {"threadId": thread_id})
        try:
            async for item in pump_queue_events(request, queue, done_event):
                yield item
        finally:
            transport["connected"] = False
        if not await request.is_disconnected() and terminal["status"] not in {"failed", "cancelled"}:
            yield sse_event("done", {"threadId": thread_id, "status": terminal["status"]})

    return EventSourceResponse(event_generator())
