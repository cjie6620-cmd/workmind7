"""Knowledge SSE 引用和历史持久化契约测试。"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.auth.models import UserContext
from app.routes.knowledge import _serialize_sources, rag_stream
from app.schemas.requests import KnowledgeQueryRequest


class _ConnectedRequest:
    async def is_disconnected(self):
        return False


async def _events(response):
    return [event async for event in response.body_iterator]


def test_sources_should_expose_one_score_field():
    sources = _serialize_sources(
        [
            {
                "content": "content",
                "title": "制度",
                "docId": "doc-1",
                "category": "HR",
                "rerank_score": 0.91234,
                "vector_score": 0.7,
            }
        ]
    )

    assert sources == [
        {
            "content": "content",
            "title": "制度",
            "docId": "doc-1",
            "category": "HR",
            "score": 0.9123,
        }
    ]


@pytest.mark.asyncio
async def test_no_sources_done_should_include_session_and_persist_empty_sources():
    save_message = AsyncMock()
    request = KnowledgeQueryRequest(question="问题", sessionId="knowledge_u-1_s")
    user = UserContext(user_id="u-1", username="user", role="user")

    with (
        patch("app.routes.knowledge.assert_session_owner", new=AsyncMock()),
        patch("app.routes.knowledge.save_message", new=save_message),
        patch(
            "app.routes.knowledge.rag_query_stream",
            new=AsyncMock(return_value={"sources": [], "stream_answer": None}),
        ),
    ):
        response = await rag_stream(request, _ConnectedRequest(), user)
        events = await _events(response)

    done = next(event for event in events if event.event == "done")
    assert json.loads(done.data)["sessionId"] == "knowledge_u-1_s"
    assistant_call = next(call for call in save_message.await_args_list if call.args[1] == "assistant")
    assert assistant_call.kwargs["metadata"] == {"sources": []}


@pytest.mark.asyncio
async def test_sources_event_and_history_metadata_should_share_contract():
    async def stream_answer():
        yield "回答"

    save_message = AsyncMock()
    request = KnowledgeQueryRequest(question="问题", sessionId="knowledge_u-1_s")
    user = UserContext(user_id="u-1", username="user", role="user")
    result = {
        "sources": [{"title": "制度", "content": "正文", "rerank_score": 0.8}],
        "stream_answer": stream_answer,
    }

    with (
        patch("app.routes.knowledge.assert_session_owner", new=AsyncMock()),
        patch("app.routes.knowledge.save_message", new=save_message),
        patch("app.routes.knowledge.rag_query_stream", new=AsyncMock(return_value=result)),
    ):
        response = await rag_stream(request, _ConnectedRequest(), user)
        events = await _events(response)

    public_sources = json.loads(next(event for event in events if event.event == "sources").data)["sources"]
    assistant_call = next(call for call in save_message.await_args_list if call.args[1] == "assistant")
    assert assistant_call.kwargs["metadata"]["sources"] == public_sources
    assert public_sources[0]["score"] == 0.8
