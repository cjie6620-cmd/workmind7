"""
Agent 路由模块

提供任务 Agent 执行功能：
- POST /run: 启动 Agent 执行任务（SSE 流式）
- GET /tools: 获取可用工具列表
- GET /examples: 获取任务示例

Agent 基于 ReAct 模式（Reasoning + Acting）：
1. 理解任务需求
2. 决定是否调用工具
3. 执行工具获取结果
4. 根据结果决定下一步
5. 重复直到任务完成

最多执行 8 步工具调用，防止无限循环。
"""

import asyncio
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sse_starlette.event import JSONServerSentEvent
from sse_starlette.sse import EventSourceResponse

from ..auth.dependencies import get_current_user
from ..auth.models import UserContext
from ..services.agent.agent import run_agent, get_tool_list
from ..services.agent.tools import AVAILABLE_TOOL_NAMES
from ..services.chat.memory import save_message, get_session_info
from ..services.config.config_service import get_config, list_configs as list_agent_configs
from ..middleware import check_injection
from ..utils.business_time import business_now
from ..schemas.requests import AgentRunRequest
from ..utils.sse import sse_event, sse_error
from ..utils.sse_disconnect import pump_queue_events
from ..utils.logger import logger
from ..utils.session_guard import assert_session_owner
from ..utils.agent_context import agent_user_scope

agent_router = APIRouter()

# 强引用后台 Agent 任务，避免客户端断连后被 GC；断连只停推送，不取消业务。
_agent_tasks: set[asyncio.Task] = set()


def _report_content_disposition(title: str) -> str:
    """生成兼容 Unicode 文件名且符合 HTTP 规范的下载响应头。"""
    filename = f"{str(title).strip() or 'report'}.md"
    encoded_filename = quote(filename, safe="")
    return f"attachment; filename=\"report.md\"; filename*=UTF-8''{encoded_filename}"


async def _resolve_agent_config(config_id: str | None) -> tuple[dict | None, dict | None]:
    """解析用户选择的 active Agent 配置，并返回运行配置和公开元数据。"""
    if not config_id:
        return None, None
    config = await get_config(config_id)
    if not config or config.get("configType") != "agent":
        raise LookupError("Agent 配置不存在")
    if not config.get("isActive"):
        raise RuntimeError("Agent 配置已停用")
    return config["configJson"], {
        "id": config["id"],
        "name": config["name"],
        "version": config["version"],
    }


@agent_router.post("/run")
async def agent_run(
    req: AgentRunRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """
    启动 Agent 执行任务

    第一步：参数校验（空值、长度、Prompt 注入检测）
    第二步：创建异步队列，后台启动 Agent 执行任务
    第三步：SSE 流式推送事件（start → tool_call/tool_result/token → done）

    SSE 事件：
    - start: 任务开始
    - tool_call: 工具调用
    - tool_result: 工具执行结果
    - token: 响应 token
    - done: 执行完成
    """
    task = req.task.strip()
    session_id = req.sessionId or f"agent_{user.user_id}_{uuid.uuid4().hex[:12]}"

    await assert_session_owner(session_id, user.user_id)

    # 参数校验
    if not task:
        return JSONResponse(status_code=400, content={"error": {"message": "任务不能为空"}})
    if len(task) > 2000:
        return JSONResponse(status_code=400, content={"error": {"message": "任务描述过长，请简洁描述"}})
    if check_injection(task):
        return JSONResponse(status_code=400, content={"error": {"message": "输入内容不符合使用规范"}})

    try:
        runtime_config, config_meta = await _resolve_agent_config(req.configId)
    except LookupError as err:
        return JSONResponse(status_code=404, content={"error": {"message": str(err)}})
    except RuntimeError as err:
        return JSONResponse(status_code=409, content={"error": {"message": str(err)}})

    # 使用队列 + 事件机制实现异步通信
    queue: asyncio.Queue[JSONServerSentEvent] = asyncio.Queue()
    done_event = asyncio.Event()
    failed_event = asyncio.Event()
    full_answer = []  # 收集完整回答
    done_payload: dict[str, object] = {}

    async def collect_event(event_type, data):
        """收集 Agent 发出的事件到队列"""
        if event_type == "done":
            done_payload.clear()
            done_payload.update(data or {})
            return
        if event_type == "token":
            full_answer.append(data.get("token", ""))
        elif event_type == "error":
            failed_event.set()
        await queue.put(sse_event(event_type, data))

    async def run_task():
        """后台执行 Agent 任务"""
        try:
            async with agent_user_scope(user.user_id):
                await save_message(session_id, "user", task, user_id=user.user_id)
                if runtime_config is None:
                    await run_agent(task, collect_event)
                else:
                    await run_agent(task, collect_event, runtime_config)
        except asyncio.CancelledError:
            logger.info("agent route: task cancelled", {"sessionId": session_id})
            raise
        except Exception as err:
            failed_event.set()
            logger.error("agent route: task failed", {"error": str(err)})
            await queue.put(sse_error(err))
        finally:
            try:
                answer_text = "".join(full_answer)
                if answer_text:
                    await save_message(session_id, "assistant", answer_text, user_id=user.user_id)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                failed_event.set()
                logger.error("agent route: persist answer failed", {"error": str(err)})
                await queue.put(sse_error(err))
            finally:
                done_event.set()

    run_task_handle = asyncio.create_task(run_task(), name=f"agent-run-{session_id}")
    _agent_tasks.add(run_task_handle)
    run_task_handle.add_done_callback(_agent_tasks.discard)

    async def event_generator():
        """SSE 事件生成器：浏览器断连只停止推送，不取消后台 Agent。"""
        yield sse_event(
            "start",
            {
                "task": task,
                "sessionId": session_id,
                "config": config_meta,
                "timestamp": business_now().isoformat(),
            },
        )
        async for item in pump_queue_events(request, queue, done_event):
            yield item
        if not await request.is_disconnected() and done_event.is_set() and not failed_event.is_set():
            yield sse_event("done", {**done_payload, "sessionId": session_id})

    return EventSourceResponse(event_generator())


@agent_router.get("/tools")
async def agent_tools():
    """获取所有可用工具列表（名称、标签、描述）"""
    return {"tools": get_tool_list()}


@agent_router.get("/configs")
async def agent_config_list():
    """获取所有 Agent 配置（从 agent_configs 表）"""
    configs = await list_agent_configs("agent")
    # 转换为前端可直接使用的格式
    result = []
    for c in configs:
        if not c.get("isActive"):
            continue
        cj = c["configJson"]
        configured_tools = cj.get("tools", [])
        result.append(
            {
                "id": c["id"],
                "name": c["name"],
                "description": cj.get("description", ""),
                "systemPrompt": cj.get("systemPrompt", ""),
                "tools": [tool for tool in configured_tools if tool in AVAILABLE_TOOL_NAMES],
                "unavailableTools": [tool for tool in configured_tools if tool not in AVAILABLE_TOOL_NAMES],
                "modelParams": cj.get("modelParams", {}),
                "isActive": c["isActive"],
                "version": c["version"],
                "updatedAt": c["updatedAt"],
            }
        )
    return {"configs": result}


@agent_router.get("/examples")
async def agent_examples():
    """
    获取任务示例

    展示 Agent 的典型使用场景：
    - 技术调研
    - 费用计算
    - 工期计算
    - 知识查询
    """
    return {
        "examples": [
            {
                "title": "技术调研",
                "task": "对比 Vue3 和 React 2024年的最新状态，分别查询它们的最新版本和主要特性，生成一份技术选型报告",
                "icon": "🔍",
            },
            {
                "title": "费用计算",
                "task": "我出差3天，酒店每晚580元，机票往返1200元，餐费每天150元，帮我计算总报销金额，并查询一下公司差旅报销标准",
                "icon": "💰",
            },
            {
                "title": "工期计算",
                "task": "项目计划从2024年3月1日开始，需要45个工作日完成，帮我计算预计完成日期，并生成一份项目时间轴摘要",
                "icon": "📅",
            },
            {
                "title": "知识查询",
                "task": "从知识库查询公司的年假政策，并计算我今年还剩多少年假（假设今年已用6天，总共15天）",
                "icon": "📚",
            },
        ]
    }


# ── 报告管理 ─────────────────────────────────────────────────


@agent_router.get("/reports")
async def agent_reports(user: UserContext = Depends(get_current_user)):
    """列出当前用户 Agent 生成的报告（仅元数据）"""
    from ..services.agent.report_store import list_reports

    return {"reports": list_reports(user.user_id)}


@agent_router.get("/reports/{report_id}")
async def agent_report_detail(report_id: str, user: UserContext = Depends(get_current_user)):
    """获取单个报告的完整内容"""
    from ..services.agent.report_store import get_report

    report = get_report(report_id, user.user_id)
    if not report:
        return JSONResponse(status_code=404, content={"error": {"message": "报告不存在或已过期"}})
    return {"report": report}


@agent_router.get("/reports/{report_id}/download")
async def agent_report_download(report_id: str, user: UserContext = Depends(get_current_user)):
    """下载报告为 Markdown 文件"""
    from ..services.agent.report_store import get_report
    from fastapi.responses import Response

    report = get_report(report_id, user.user_id)
    if not report:
        return JSONResponse(status_code=404, content={"error": {"message": "报告不存在或已过期"}})
    title = report["meta"]["title"]
    content = report["content"]
    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": _report_content_disposition(title)},
    )


@agent_router.delete("/reports/{report_id}")
async def agent_report_delete(report_id: str, user: UserContext = Depends(get_current_user)):
    """删除报告"""
    from ..services.agent.report_store import delete_report

    ok = delete_report(report_id, user.user_id)
    if not ok:
        return JSONResponse(status_code=500, content={"error": {"message": "删除失败"}})
    return {"success": True}


@agent_router.get("/history/{session_id}")
async def get_agent_history(session_id: str, user: UserContext = Depends(get_current_user)):
    """获取 Agent 任务历史"""
    await assert_session_owner(session_id, user.user_id)
    info = await get_session_info(session_id)
    return info


@agent_router.get("/sessions")
async def get_agent_sessions(user: UserContext = Depends(get_current_user)):
    """获取当前用户的 Agent 会话列表"""
    from sqlalchemy import select, func
    from ..core.database import async_session_factory
    from ..models.entities import Conversation

    async with async_session_factory() as session:
        result = await session.execute(
            select(
                Conversation.session_id,
                func.count(Conversation.id).label("msg_count"),
                func.min(Conversation.created_at).label("created_at"),
            )
            .where(Conversation.session_id.like("agent_%"))
            .where(Conversation.user_id == user.user_id)
            .group_by(Conversation.session_id)
            .order_by(func.min(Conversation.created_at).desc())
        )
        rows = result.all()

        sessions = []
        for row in rows:
            sid = row[0]
            r = await session.execute(
                select(Conversation.content)
                .where(Conversation.session_id == sid)
                .where(Conversation.role == "user")
                .order_by(Conversation.created_at)
                .limit(1)
            )
            first_msg = r.scalar_one_or_none()
            title = first_msg[:30] + ("..." if first_msg and len(first_msg) > 30 else "") if first_msg else "Agent 任务"
            sessions.append(
                {
                    "id": sid,
                    "title": title,
                    "messageCount": row[1],
                    "createdAt": row[2].isoformat() if row[2] else None,
                }
            )

    return {"sessions": sessions}
