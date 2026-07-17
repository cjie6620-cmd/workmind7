"""
会话 IDOR 防护集成测试
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def enable_auth():
    from app.config import config

    saved = {
        "enabled": config["auth"]["enabled"],
        "secret": config["auth"]["jwt_secret"],
    }
    config["auth"]["enabled"] = True
    config["auth"]["jwt_secret"] = "test-jwt-secret-must-be-at-least-32-chars"
    yield
    config["auth"]["enabled"] = saved["enabled"]
    config["auth"]["jwt_secret"] = saved["secret"]


@pytest.fixture
async def auth_client(enable_auth):
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    response = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def _auth_header(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_forbid_cross_user_chat_history(auth_client):
    """user B 无法读取 user A 的 chat 历史"""
    tokens_user = await _login(auth_client, "user", "user123")
    tokens_admin = await _login(auth_client, "admin", "admin123")
    session_id = "session_user_1234567890"

    with patch("app.utils.session_guard.get_session_owner", new_callable=AsyncMock, return_value="user"):
        response = await auth_client.get(
            f"/api/chat/history/{session_id}",
            headers=_auth_header(tokens_admin["accessToken"]),
        )

    assert response.status_code == 403
    assert response.json()["detail"]["error"]["code"] == "FORBIDDEN"

    own = await auth_client.get(
        f"/api/chat/history/{session_id}",
        headers=_auth_header(tokens_user["accessToken"]),
    )
    assert own.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_forbid_cross_user_chat_stream(auth_client):
    """user B 无法向 user A 的 session 发消息"""
    tokens_admin = await _login(auth_client, "admin", "admin123")
    session_id = "session_user_1234567890"

    with patch("app.utils.session_guard.get_session_owner", new_callable=AsyncMock, return_value="user"):
        response = await auth_client.post(
            "/api/chat/stream",
            json={"message": "hello", "sessionId": session_id},
            headers=_auth_header(tokens_admin["accessToken"]),
        )

    assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_forbid_legacy_session_id_without_prefix(auth_client):
    """无用户前缀的 legacy sessionId 应拒绝"""
    tokens = await _login(auth_client, "user", "user123")

    with patch("app.utils.session_guard.get_session_owner", new_callable=AsyncMock, return_value=None):
        response = await auth_client.get(
            "/api/chat/history/knowledge_abc123",
            headers=_auth_header(tokens["accessToken"]),
        )

    assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_allow_prefixed_empty_session(auth_client):
    """带本人前缀的新会话（尚无 DB 记录）应允许"""
    from app.utils.session_guard import assert_session_owner

    await assert_session_owner("session_user_new123", "user")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_forbid_cross_user_knowledge_history(auth_client):
    """user B 无法读取 user A 的知识库历史"""
    await _login(auth_client, "user", "user123")
    tokens_admin = await _login(auth_client, "admin", "admin123")
    session_id = "knowledge_user_abc123"

    with patch("app.utils.session_guard.get_session_owner", new_callable=AsyncMock, return_value="user"):
        response = await auth_client.get(
            f"/api/knowledge/history/{session_id}",
            headers=_auth_header(tokens_admin["accessToken"]),
        )

    assert response.status_code == 403
