"""ERP AI 预审路由。

该模块提供报销/请假表单解析和 AI 审批预演。预演结果不等同于组织内的
正式审批；正式上线仍需接入真实审批人、待办、审计和撤回/补件状态机。
"""

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sse_starlette.sse import EventSourceResponse

from ..auth.dependencies import get_current_user
from ..auth.models import UserContext
from ..core.database import async_session_factory
from ..models.entities import ApprovalRecord
from ..schemas.requests import ErpParseRequest, ErpSubmitRequest
from ..services.erp.approval import APPROVAL_ROLES, run_approval_flow
from ..services.erp.parser import (
    ExpenseForm,
    LeaveForm,
    parse_expense_form,
    parse_leave_form,
)
from ..utils.background_tasks import wait_or_cancel_tasks
from ..utils.logger import logger
from ..utils.sse import sse_error, sse_event
from ..utils.sse_disconnect import pump_queue_events

erp_router = APIRouter()

# 保留强引用，确保客户端断开后已经接受的申请仍能完成并落库。
_approval_tasks: set[asyncio.Task] = set()


async def shutdown_approval_tasks(timeout_seconds: float = 20) -> None:
    """优雅停机：给预审短暂完成窗口，超时后取消并由任务写入 failed。"""
    await wait_or_cancel_tasks(_approval_tasks, timeout_seconds)


def _validated_form(form_type: str, form_data: dict) -> dict:
    """按表单类型强校验，并返回可写入 JSONB 的规范化 camelCase 数据。"""
    model: ExpenseForm | LeaveForm
    if form_type == "expense":
        model = ExpenseForm.model_validate(form_data)
    elif form_type == "leave":
        model = LeaveForm.model_validate(form_data)
    else:
        raise ValueError("formType 必须是 expense 或 leave")
    return model.model_dump(mode="json", by_alias=True, exclude={"warnings"})


async def _find_by_request(user_id: str, request_id: str | None) -> ApprovalRecord | None:
    """按 (user_id, request_id) 幂等键查找已存在的申请，用于重复提交复用。"""
    if not request_id:
        return None
    async with async_session_factory() as session:
        result = await session.execute(
            select(ApprovalRecord)
            .where(ApprovalRecord.user_id == user_id)
            .where(ApprovalRecord.request_id == request_id)
        )
        return result.scalar_one_or_none()


async def _locked_approval(session, app_id: str) -> ApprovalRecord | None:
    """行锁读取审批记录：事件快照与终态写入都经此串行化，防并发覆盖。"""
    return await session.scalar(select(ApprovalRecord).where(ApprovalRecord.session_id == app_id).with_for_update())


def _detail(record: ApprovalRecord) -> dict:
    """将 ORM 记录转换为前端申请详情契约（messages/result 取自 result_json 快照）。"""
    result_json = record.result_json or {}
    return {
        "id": record.session_id,
        "formType": record.form_type,
        "formData": record.form_data,
        "status": record.status,
        "messages": result_json.get("messages", []),
        "result": result_json.get("result"),
        "simulation": True,
        "createdAt": record.created_at.isoformat() if record.created_at else None,
        "updatedAt": record.completed_at.isoformat() if record.completed_at else None,
    }


def _duplicate_response(record: ApprovalRecord) -> EventSourceResponse:
    """同一幂等请求不会再次执行模型，只返回现有申请状态。"""

    async def generator():
        yield sse_event(
            "start",
            {
                "appId": record.session_id,
                "formType": record.form_type,
                "duplicate": True,
            },
        )
        result = (record.result_json or {}).get("result")
        if result:
            yield sse_event("final", result)
        yield sse_event(
            "done",
            {
                "appId": record.session_id,
                "status": record.status,
                "duplicate": True,
            },
        )

    return EventSourceResponse(generator())


@erp_router.post("/parse")
async def erp_parse(req: ErpParseRequest):
    """把自然语言解析为经过强类型校验的报销或请假表单。"""
    text = req.text.strip()
    form_type = req.formType

    if form_type not in ("expense", "leave"):
        return JSONResponse(status_code=400, content={"error": {"message": "formType 必须是 expense 或 leave"}})

    try:
        form = await (parse_expense_form(text) if form_type == "expense" else parse_leave_form(text))
        form_dict = form.model_dump(mode="json", by_alias=True, exclude={"warnings"})
        return {"success": True, "form": form_dict, "formType": form_type}
    except (ValueError, ValidationError) as err:
        logger.warning("erp: form parse validation failed", {"error": str(err), "formType": form_type})
        return JSONResponse(
            status_code=422,
            content={"error": {"message": "无法识别为有效表单，请检查金额、日期和必填项"}},
        )
    except Exception as err:
        logger.error("erp: parse error", {"error": str(err), "formType": form_type})
        return JSONResponse(status_code=500, content={"error": {"message": "解析失败，请稍后重试"}})


@erp_router.post("/submit/stream")
async def erp_submit_stream(
    req: ErpSubmitRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """提交 AI 预审；先持久化 pending，再异步执行，断连不会撤销申请。"""
    try:
        form_data = _validated_form(req.formType, req.formData)
    except ValueError as err:
        return JSONResponse(status_code=400, content={"error": {"message": str(err)}})
    except ValidationError as err:
        logger.info("erp: submit validation failed", {"userId": user.user_id, "errors": err.errors()})
        return JSONResponse(
            status_code=422,
            content={"error": {"message": "表单校验失败，请检查金额、日期范围和必填项"}},
        )

    # 申请人身份完全由认证上下文派生，忽略客户端 applicantName。
    form_data["applicantName"] = user.username
    request_id = req.requestId or req.sessionId

    existing = await _find_by_request(user.user_id, request_id)
    if existing:
        return _duplicate_response(existing)

    app_id = f"APP_{uuid.uuid4().hex}"
    record = ApprovalRecord(
        session_id=app_id,
        user_id=user.user_id,
        request_id=request_id,
        form_type=req.formType,
        form_data=form_data,
        flow_json={"approverIds": []},
        approvers={"items": []},
        status="pending",
        result_json={"messages": [], "simulation": True},
    )

    try:
        async with async_session_factory() as session:
            session.add(record)
            await session.commit()
    except IntegrityError:
        # 并发重试由数据库唯一约束仲裁，后发请求复用首个申请。
        existing = await _find_by_request(user.user_id, request_id)
        if existing:
            return _duplicate_response(existing)
        raise

    queue: asyncio.Queue = asyncio.Queue()
    done_event = asyncio.Event()
    messages: list[dict] = []
    terminal: dict[str, str] = {"status": "pending"}

    async def collect_event(event_type: str, data: dict):
        await queue.put(sse_event(event_type, data))
        if event_type == "message":
            messages.append(data)

        # 每个业务事件都刷新数据库快照，进程异常时仍可看到最后进度。
        if event_type in {"plan", "message", "approver_done"}:
            async with async_session_factory() as session:
                db_record = await _locked_approval(session, app_id)
                if not db_record:
                    raise RuntimeError("审批记录不存在")
                current_result = dict(db_record.result_json or {})
                current_result["messages"] = list(messages)
                if event_type == "plan":
                    approvers = data.get("approvers", [])
                    db_record.flow_json = {
                        "approverIds": [item.get("id") for item in approvers],
                    }
                    db_record.approvers = {"items": approvers}
                db_record.result_json = current_result
                await session.commit()

    async def mark_failed(message: str):
        terminal["status"] = "failed"
        try:
            async with async_session_factory() as session:
                db_record = await _locked_approval(session, app_id)
                if db_record:
                    db_record.status = "failed"
                    db_record.final_comment = message
                    db_record.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    db_record.result_json = {
                        "messages": list(messages),
                        "simulation": True,
                        "error": message,
                    }
                    await session.commit()
        except Exception as persist_err:
            logger.error(
                "erp: failed status persistence error",
                {
                    "appId": app_id,
                    "error": str(persist_err),
                },
            )

    async def run():
        try:
            result = await run_approval_flow(form_data, req.formType, collect_event, app_id)
            async with async_session_factory() as session:
                db_record = await _locked_approval(session, app_id)
                if not db_record:
                    raise RuntimeError("审批记录不存在")
                db_record.status = result["status"]
                db_record.final_comment = result.get("comment")
                db_record.flow_json = {"approverIds": result.get("approverIds", [])}
                db_record.approvers = {"items": result.get("approvers", [])}
                db_record.result_json = {
                    "result": result,
                    "messages": list(messages),
                    "simulation": True,
                }
                db_record.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()
            terminal["status"] = result["status"]
        except asyncio.CancelledError:
            await mark_failed("服务关闭导致预审中断，请重新提交")
            raise
        except Exception as err:
            logger.error("erp: approval error", {"error": str(err), "appId": app_id})
            await mark_failed("AI 预审执行失败，请稍后重新提交")
            await queue.put(sse_error(err))
        finally:
            done_event.set()

    run_task = asyncio.create_task(run(), name=f"erp-approval-{app_id}")
    _approval_tasks.add(run_task)
    run_task.add_done_callback(_approval_tasks.discard)

    async def event_generator():
        yield sse_event(
            "start",
            {
                "appId": app_id,
                "formType": req.formType,
                "simulation": True,
            },
        )
        # ERP 提交是已接受的业务命令；浏览器断连只停止推送，不取消后台任务。
        async for item in pump_queue_events(request, queue, done_event):
            yield item
        if not await request.is_disconnected() and terminal["status"] not in {"failed", "cancelled"}:
            yield sse_event("done", {"appId": app_id, "status": terminal["status"]})

    return EventSourceResponse(event_generator())


@erp_router.get("/applications")
async def list_applications(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: UserContext = Depends(get_current_user),
):
    """普通用户只看自己的记录；管理员可查看全部预审记录。"""
    allowed_statuses = {"pending", "approved", "rejected", "needs_info", "failed"}
    if status and status not in allowed_statuses:
        return JSONResponse(status_code=400, content={"error": {"message": "无效的申请状态"}})

    stmt = select(ApprovalRecord).order_by(desc(ApprovalRecord.created_at)).limit(limit)
    if user.role != "admin":
        stmt = stmt.where(ApprovalRecord.user_id == user.user_id)
    if status:
        stmt = stmt.where(ApprovalRecord.status == status)

    async with async_session_factory() as session:
        result = await session.execute(stmt)
        records = result.scalars().all()

    return {
        "applications": [
            {
                "id": record.session_id,
                "formType": record.form_type,
                "status": record.status,
                "amount": record.form_data.get("totalAmount"),
                "reason": record.form_data.get("reason"),
                "days": record.form_data.get("workdays"),
                "applicantName": record.form_data.get("applicantName"),
                "simulation": True,
                "createdAt": record.created_at.isoformat() if record.created_at else None,
            }
            for record in records
        ]
    }


@erp_router.get("/applications/{app_id}")
async def get_application(
    app_id: str,
    user: UserContext = Depends(get_current_user),
):
    """查询单条预审记录，并执行所有权校验。"""
    async with async_session_factory() as session:
        result = await session.execute(select(ApprovalRecord).where(ApprovalRecord.session_id == app_id))
        record = result.scalar_one_or_none()

    # 对非所有者统一返回 404，避免枚举其他用户申请 ID。
    if not record or (user.role != "admin" and record.user_id != user.user_id):
        return JSONResponse(status_code=404, content={"error": {"message": "申请不存在"}})
    return _detail(record)


@erp_router.get("/roles")
async def erp_roles():
    """返回 AI 预演使用的角色定义，不代表真实组织审批人。"""
    return {"roles": list(APPROVAL_ROLES.values()), "simulation": True}
