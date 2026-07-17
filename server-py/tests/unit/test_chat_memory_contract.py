"""对话历史返回与会话所有权查询测试。"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.chat.memory import get_history_db, list_sessions


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_history_should_return_message_metadata():
    row = SimpleNamespace(
        id="message-id",
        role="assistant",
        content="answer",
        model="deepseek-chat",
        tokens=10,
        metadata_={"sources": [{"title": "制度", "score": 0.9}]},
        created_at=datetime(2026, 1, 1),
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    session = AsyncMock()
    session.execute.return_value = result

    with patch(
        "app.services.chat.memory.async_session_factory",
        return_value=_AsyncSessionContext(session),
    ):
        history = await get_history_db("session-a")

    assert history[0]["metadata"] == {"sources": [{"title": "制度", "score": 0.9}]}


@pytest.mark.asyncio
async def test_session_title_query_should_filter_by_user_id():
    aggregate_result = MagicMock()
    aggregate_result.all.return_value = [("shared-session", 2, datetime(2026, 1, 1))]
    title_result = MagicMock()
    title_result.scalar_one_or_none.return_value = "我的问题"
    session = AsyncMock()
    session.execute.side_effect = [aggregate_result, title_result]

    with patch(
        "app.services.chat.memory.async_session_factory",
        return_value=_AsyncSessionContext(session),
    ):
        sessions = await list_sessions(user_id="user-a")

    title_statement = session.execute.await_args_list[1].args[0]
    assert "conversations.user_id" in str(title_statement)
    assert sessions[0]["title"] == "我的问题"
