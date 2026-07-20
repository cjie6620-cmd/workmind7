"""
对话路由模块

提供智能对话功能：
- POST /stream: 流式对话（精确缓存、会话历史、用户画像注入、角色系统提示）
- GET/POST/DELETE /sessions: 会话列表 / 新建 / 删除
- GET /history/{session_id}: 会话历史
- GET/DELETE /profile: 用户画像查看 / 清除
- POST /messages/{id}/feedback: 回答点赞点踩
- GET /roles: 内置角色列表

流式契约：start → token* → done（或 error）；缓存命中走 cache_hit → token* → done。
断连时已生成的部分回复带 incomplete 标记落库，用户输入永远先于模型调用落库。
"""

import asyncio
import time
import uuid

from fastapi import APIRouter, Depends, Request
from langchain_core.messages import HumanMessage, SystemMessage
from sse_starlette.sse import EventSourceResponse

from ..auth.dependencies import get_current_user
from ..auth.models import UserContext
from ..config import config
from ..services.model import get_chat_model
from ..services.cache import build_cache_context, cache
from ..services.usage_monitor import record_api_call
from ..services.chat.memory import (
    get_history_db,
    trim_history,
    clear_history,
    get_profile,
    get_profile_camel,
    profile_to_context,
    fire_and_forget_profile,
    clear_profile,
    list_sessions,
    save_message,
    set_message_feedback,
)
from ..middleware import check_injection
from ..schemas.requests import ChatFeedbackRequest, ChatRequest
from ..utils.sse import sse_event, sse_error
from ..utils.logger import logger
from ..utils.session_guard import assert_session_owner, normalize_chat_session_id
from ..utils.responses import error_response

chat_router = APIRouter()

ROLES = {
    "default": "你是 Mr.Chen AI，一个智能办公助手，回答简洁专业。",
    "tech": "你是资深技术顾问，精通 Vue3、React、Node.js 等前端技术栈。回答要有代码示例，说明清楚原理。",
    "hr": "你是 HR 助理，熟悉劳动法规、公司政策、绩效管理、招聘流程。回答要有温度，兼顾政策合规和员工关怀。",
    "legal": "你是法务助理，熟悉合同法、知识产权、劳动合同。回答要严谨，必要时建议咨询专业律师。",
}


@chat_router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """流式对话接口"""
    message = req.message
    session_id = normalize_chat_session_id(req.sessionId, user.user_id)
    role = req.role
    user_id = user.user_id

    if check_injection(message):
        return error_response(400, "输入内容不符合使用规范")

    await assert_session_owner(session_id, user_id)

    async def event_generator():
        try:
            # 第一步：拼装系统提示（角色模板 + 用户画像）与裁剪后的会话上下文
            base_system = ROLES.get(role, ROLES["default"])
            profile = await get_profile(user_id)
            profile_ctx = profile_to_context(profile)
            system_prompt = base_system + profile_ctx
            # 只取最近 50 条构建上下文，避免长会话每条消息都全量拉回；再按 token 预算裁剪
            raw_history = await get_history_db(session_id, limit=50)
            history_msgs = [{"role": msg["role"], "content": msg["content"]} for msg in raw_history]
            trimmed = trim_history(history_msgs, 2000)
            model_name = config["ai"]["primary_model"]
            cache_context = build_cache_context(
                user_id=user_id,
                session_id=session_id,
                system_prompt=system_prompt,
                message=message,
                history=trimmed,
                model_context={"name": model_name, "temperature": 0.7},
            )

            # 第二步：精确缓存命中则按打字机节奏回放，不再调用模型
            cached = await asyncio.to_thread(cache.get, cache_context)
            if cached:
                logger.info("cache hit", {"sessionId": session_id, "msg": message[:30]})
                # 记录一条 from_cache 监控行，使看板缓存命中率非零；token 记 0（已省下，不计费）。
                record_api_call(feature="chat", from_cache=True, model_name=model_name, latency_ms=0)
                await save_message(session_id, "user", message, user_id=user_id)
                yield sse_event("cache_hit", {})
                content = cached["content"]
                delivered = ""
                for i in range(0, len(content), 3):
                    if await request.is_disconnected():
                        if delivered:
                            await save_message(
                                session_id,
                                "assistant",
                                delivered,
                                model=model_name,
                                metadata={"fromCache": True, "incomplete": True},
                                user_id=user_id,
                            )
                        return
                    token = content[i : i + 3]
                    delivered += token
                    yield sse_event("token", {"token": token})
                    await asyncio.sleep(0.006)

                assistant_message_id = await save_message(
                    session_id,
                    "assistant",
                    content,
                    model=model_name,
                    metadata={"fromCache": True},
                    user_id=user_id,
                )
                fire_and_forget_profile(user_id, message, content)
                yield sse_event(
                    "done",
                    {
                        "sessionId": session_id,
                        "assistantMessageId": assistant_message_id,
                        "fromCache": True,
                    },
                )
                return

            # 第三步：未命中缓存，流式调用模型并逐 token 推送
            messages = [SystemMessage(system_prompt), *trimmed, HumanMessage(message)]

            # 用户消息在模型调用前落库；Provider 失败或用户停止时也不会丢失输入。
            await save_message(session_id, "user", message, user_id=user_id)
            yield sse_event("start", {"sessionId": session_id})

            full_reply = ""
            input_tokens = 0
            output_tokens = 0
            disconnected = False

            try:
                async for chunk in get_chat_model().astream(messages):
                    if await request.is_disconnected():
                        disconnected = True
                        break
                    if chunk.content:
                        full_reply += chunk.content
                        yield sse_event("token", {"token": chunk.content})
                    if chunk.usage_metadata:
                        input_tokens = chunk.usage_metadata.get("input_tokens", 0) or 0
                        output_tokens = chunk.usage_metadata.get("output_tokens", 0) or 0
            except Exception:
                if full_reply:
                    await save_message(
                        session_id,
                        "assistant",
                        full_reply,
                        model=model_name,
                        tokens=output_tokens,
                        metadata={"incomplete": True, "reason": "provider_error"},
                        user_id=user_id,
                    )
                raise

            if disconnected or await request.is_disconnected():
                if full_reply:
                    await save_message(
                        session_id,
                        "assistant",
                        full_reply,
                        model=model_name,
                        tokens=output_tokens,
                        metadata={"incomplete": True, "reason": "client_stopped"},
                        user_id=user_id,
                    )
                return

            # 第四步：完整回复落库、写缓存、异步更新画像，最后发 done 终态
            assistant_message_id = await save_message(
                session_id,
                "assistant",
                full_reply,
                model=model_name,
                tokens=output_tokens,
                user_id=user_id,
            )

            await asyncio.to_thread(
                cache.set,
                cache_context,
                {
                    "content": full_reply,
                    "tokens": input_tokens + output_tokens,
                },
            )

            fire_and_forget_profile(user_id, message, full_reply)

            yield sse_event(
                "done",
                {
                    "sessionId": session_id,
                    "assistantMessageId": assistant_message_id,
                    "fromCache": False,
                    "inputTokens": input_tokens,
                    "outputTokens": output_tokens,
                },
            )
            logger.info(
                "chat done",
                {
                    "sessionId": session_id,
                    "inputTokens": input_tokens,
                    "outputTokens": output_tokens,
                    "replyLen": len(full_reply),
                },
            )
        except Exception as err:
            logger.error("chat error", {"error": str(err)})
            yield sse_error(err)

    return EventSourceResponse(event_generator())


@chat_router.get("/sessions")
async def get_sessions(user: UserContext = Depends(get_current_user)):
    """获取当前用户的会话列表"""
    sessions = await list_sessions(user_id=user.user_id)
    return {"sessions": sessions}


@chat_router.post("/sessions")
async def create_session(user: UserContext = Depends(get_current_user)):
    """创建新会话"""
    session_id = f"session_{user.user_id}_{uuid.uuid4().hex}"
    return {"id": session_id, "title": "新对话", "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ")}


@chat_router.get("/history/{session_id}")
async def get_history_endpoint(session_id: str, user: UserContext = Depends(get_current_user)):
    """获取指定会话的历史消息"""
    await assert_session_owner(session_id, user.user_id)
    messages = await get_history_db(session_id)
    return {"messages": messages}


@chat_router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: UserContext = Depends(get_current_user)):
    """删除指定会话"""
    await assert_session_owner(session_id, user.user_id)
    await clear_history(session_id, user_id=user.user_id)
    return {"success": True}


@chat_router.get("/profile")
async def get_user_profile(user: UserContext = Depends(get_current_user)):
    """获取当前用户画像"""
    return await get_profile_camel(user.user_id)


@chat_router.delete("/profile")
async def delete_user_profile(user: UserContext = Depends(get_current_user)):
    """永久清除当前用户画像。"""
    await clear_profile(user.user_id)
    return {"success": True}


@chat_router.post("/messages/{message_id}/feedback")
async def save_chat_feedback(
    message_id: str,
    req: ChatFeedbackRequest,
    user: UserContext = Depends(get_current_user),
):
    """记录当前用户对助手回答的有用/无用反馈。"""
    updated = await set_message_feedback(message_id, user.user_id, req.rating)
    if not updated:
        return error_response(404, "消息不存在")
    return {"success": True, "rating": req.rating}


@chat_router.get("/roles")
async def get_roles():
    """获取内置角色列表"""
    return {
        "roles": [
            {"id": "default", "label": "通用助手", "icon": "🤖", "desc": "日常问答、通用任务"},
            {"id": "tech", "label": "技术顾问", "icon": "💻", "desc": "代码、架构、技术方案"},
            {"id": "hr", "label": "HR 助理", "icon": "📋", "desc": "人事政策、绩效、招聘"},
            {"id": "legal", "label": "法务助理", "icon": "⚖️", "desc": "合同、合规、法律问题"},
        ]
    }
