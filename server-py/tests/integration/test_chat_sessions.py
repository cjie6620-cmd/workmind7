"""
会话管理集成测试
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
async def app_client():
    """创建 FastAPI 测试客户端"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_delete_session_when_valid_id(app_client):
    """DELETE /api/chat/sessions/{id} 应 await clear_history"""
    session_id = "session_test_delete"

    with (
        patch("app.routes.chat.assert_session_owner", new_callable=AsyncMock),
        patch("app.routes.chat.clear_history", new_callable=AsyncMock) as mock_clear,
    ):
        response = await app_client.delete(f"/api/chat/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["success"] is True
    mock_clear.assert_awaited_once()
    args, kwargs = mock_clear.call_args
    assert args[0] == session_id
    assert kwargs.get("user_id") == "dev"
