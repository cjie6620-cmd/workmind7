"""Chat 路由缓存命中与历史错误语义测试。"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.auth.models import UserContext
from app.middleware import ChatRequest
from app.routes.chat import (
    chat_stream,
    delete_user_profile,
    get_history_endpoint,
    save_chat_feedback,
)
from app.schemas.requests import ChatFeedbackRequest


class _ConnectedRequest:
    async def is_disconnected(self):
        return False


@pytest.mark.asyncio
async def test_cache_hit_should_persist_exchange_and_return_session_id():
    save_message = AsyncMock(side_effect=["user-message-id", "assistant-message-id"])
    cache_get = MagicMock(return_value={"content": "缓存回答", "tokens": 8})
    request = ChatRequest(message="继续", sessionId="session_user1_test", role="default")
    user = UserContext(user_id="user1", username="user", role="user")

    with (
        patch("app.routes.chat.assert_session_owner", new=AsyncMock()),
        patch("app.routes.chat.get_profile", new=AsyncMock(return_value={})),
        patch(
            "app.routes.chat.get_history_db",
            new=AsyncMock(return_value=[{"role": "user", "content": "之前的问题"}]),
        ),
        patch("app.routes.chat.cache.get", new=cache_get),
        patch("app.routes.chat.save_message", new=save_message),
        patch("app.routes.chat.fire_and_forget_profile"),
        patch("app.routes.chat.asyncio.sleep", new=AsyncMock()),
    ):
        response = await chat_stream(request, _ConnectedRequest(), user)
        events = [event async for event in response.body_iterator]

    context = cache_get.call_args.args[0]
    assert context["userId"] == "user1"
    assert context["sessionId"] == "session_user1_test"
    assert context["history"] == [{"role": "user", "content": "之前的问题"}]
    assert [call.args[1] for call in save_message.await_args_list] == ["user", "assistant"]
    done = next(event for event in events if event.event == "done")
    assert json.loads(done.data) == {
        "sessionId": "session_user1_test",
        "assistantMessageId": "assistant-message-id",
        "fromCache": True,
    }


@pytest.mark.asyncio
async def test_history_database_error_should_propagate():
    user = UserContext(user_id="user1", username="user", role="user")

    with (
        patch("app.routes.chat.assert_session_owner", new=AsyncMock()),
        patch("app.routes.chat.get_history_db", new=AsyncMock(side_effect=RuntimeError("db down"))),
    ):
        with pytest.raises(RuntimeError, match="db down"):
            await get_history_endpoint("session_user1_test", user)


@pytest.mark.asyncio
async def test_profile_clear_and_feedback_are_persisted_operations():
    user = UserContext(user_id="user1", username="user", role="user")

    with patch("app.routes.chat.clear_profile", new=AsyncMock()) as clear:
        response = await delete_user_profile(user)
    clear.assert_awaited_once_with("user1")
    assert response == {"success": True}

    with patch(
        "app.routes.chat.set_message_feedback",
        new=AsyncMock(return_value=True),
    ) as feedback:
        response = await save_chat_feedback(
            "message-id",
            ChatFeedbackRequest(rating="helpful"),
            user,
        )
    feedback.assert_awaited_once_with("message-id", "user1", "helpful")
    assert response == {"success": True, "rating": "helpful"}
