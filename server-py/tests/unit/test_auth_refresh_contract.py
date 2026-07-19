"""Refresh token 必须采用数据库中的当前用户信息。"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth import dependencies as auth_dependencies
from app.auth.models import LoginRequest, RefreshRequest
from app.auth import users as user_service
from app.auth.users import AuthStoreUnavailable, StoredUser
from app.routes.auth import login, refresh


@pytest.mark.asyncio
async def test_refresh_should_issue_tokens_with_current_database_role():
    current = StoredUser(user_id="u-1", username="renamed", password="", role="user")
    request = RefreshRequest(refreshToken="x" * 10)

    with (
        patch(
            "app.routes.auth.decode_token",
            return_value={"sub": "u-1", "username": "old-name", "role": "admin", "jti": "jti-1"},
        ),
        patch("app.routes.auth.get_user_by_id", new=AsyncMock(return_value=current)) as lookup,
        patch("app.routes.auth.consume_refresh_jti", new=AsyncMock(return_value=True)) as consume,
        patch(
            "app.routes.auth._token_response",
            new=AsyncMock(
                side_effect=lambda user_id, username, role: {
                    "userId": user_id,
                    "username": username,
                    "role": role,
                }
            ),
        ),
    ):
        response = await refresh(request)

    lookup.assert_awaited_once_with("u-1")
    consume.assert_awaited_once_with("jti-1", "u-1")
    assert response == {"userId": "u-1", "username": "renamed", "role": "user"}


@pytest.mark.asyncio
async def test_refresh_should_reject_reused_or_rotated_token():
    """旧 jti 已被轮换/吊销时，refresh 必须 401，不再签发新 token。"""
    current = StoredUser(user_id="u-1", username="u", password="", role="user")
    request = RefreshRequest(refreshToken="x" * 10)

    with (
        patch(
            "app.routes.auth.decode_token",
            return_value={"sub": "u-1", "jti": "stale"},
        ),
        patch("app.routes.auth.get_user_by_id", new=AsyncMock(return_value=current)),
        patch("app.routes.auth.consume_refresh_jti", new=AsyncMock(return_value=False)),
        patch("app.routes.auth._token_response", new=AsyncMock()) as issue,
    ):
        response = await refresh(request)

    assert response.status_code == 401
    assert json.loads(response.body)["error"]["code"] == "INVALID_TOKEN"
    issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_should_reject_deleted_user():
    request = RefreshRequest(refreshToken="x" * 10)

    with (
        patch("app.routes.auth.decode_token", return_value={"sub": "deleted"}),
        patch("app.routes.auth.get_user_by_id", new=AsyncMock(return_value=None)),
    ):
        response = await refresh(request)

    assert response.status_code == 401
    assert json.loads(response.body)["error"]["code"] == "INVALID_TOKEN"


class _QueryResult:
    def scalar_one_or_none(self):
        return None


class _CapturingSession:
    def __init__(self, statements):
        self.statements = statements

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, statement):
        self.statements.append(str(statement))
        return _QueryResult()


@pytest.mark.asyncio
async def test_login_and_refresh_queries_exclude_inactive_users(monkeypatch):
    statements = []
    monkeypatch.setattr(
        user_service,
        "async_session_factory",
        lambda: _CapturingSession(statements),
    )

    assert await user_service.authenticate_db("disabled", "password") is None
    assert await user_service.get_user_by_id("disabled-id") is None

    assert len(statements) == 2
    assert all("users.is_active IS true" in statement for statement in statements)


@pytest.mark.asyncio
async def test_login_does_not_fallback_when_database_rejects_credentials(monkeypatch):
    """数据库查询成功后必须以其结果为准，不能签发不存在 subject 的 token。"""
    db_auth = AsyncMock(return_value=None)
    monkeypatch.setattr(user_service, "authenticate_db", db_auth)

    authenticated = await user_service.authenticate("user", "user123")

    assert authenticated is None
    db_auth.assert_awaited_once_with("user", "user123")


@pytest.mark.asyncio
async def test_authenticate_raises_explicit_error_when_store_is_unavailable(monkeypatch):
    db_auth = AsyncMock(side_effect=RuntimeError("database unavailable"))
    monkeypatch.setattr(user_service, "authenticate_db", db_auth)

    with pytest.raises(AuthStoreUnavailable):
        await user_service.authenticate("user", "user123")


@pytest.mark.asyncio
async def test_login_returns_401_when_database_rejects_credentials():
    request = LoginRequest(username="unknown", password="wrong-password")

    with patch("app.routes.auth.authenticate_user", new=AsyncMock(return_value=None)):
        response = await login(request)

    assert response.status_code == 401
    assert json.loads(response.body)["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_returns_503_when_auth_store_is_unavailable():
    request = LoginRequest(username="user", password="user123")

    with patch(
        "app.routes.auth.authenticate_user",
        new=AsyncMock(side_effect=AuthStoreUnavailable("认证存储不可用")),
    ):
        response = await login(request)

    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == "AUTH_STORE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_refresh_returns_503_when_auth_store_is_unavailable():
    request = RefreshRequest(refreshToken="x" * 10)

    with (
        patch("app.routes.auth.decode_token", return_value={"sub": "u-1"}),
        patch(
            "app.routes.auth.get_user_by_id",
            new=AsyncMock(side_effect=RuntimeError("database unavailable")),
        ),
    ):
        response = await refresh(request)

    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == "AUTH_STORE_UNAVAILABLE"


def _request_with_token_user(role: str = "admin") -> Request:
    request = Request({"type": "http", "headers": [], "state": {}})
    request.state.auth_user = auth_dependencies.UserContext(
        user_id="u-1",
        username="old-name",
        role=role,
    )
    return request


@pytest.mark.asyncio
async def test_protected_request_uses_current_database_role(monkeypatch):
    monkeypatch.setitem(auth_dependencies.config["auth"], "enabled", True)
    monkeypatch.setattr(
        auth_dependencies,
        "get_user_by_id",
        AsyncMock(
            return_value=StoredUser(
                user_id="u-1",
                username="current-name",
                password="",
                role="user",
            )
        ),
    )

    current = await auth_dependencies.get_current_user(_request_with_token_user("admin"))

    assert current.username == "current-name"
    assert current.role == "user"


@pytest.mark.asyncio
async def test_protected_request_rejects_disabled_user(monkeypatch):
    monkeypatch.setitem(auth_dependencies.config["auth"], "enabled", True)
    monkeypatch.setattr(auth_dependencies, "get_user_by_id", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as caught:
        await auth_dependencies.get_current_user(_request_with_token_user())

    assert caught.value.status_code == 401
