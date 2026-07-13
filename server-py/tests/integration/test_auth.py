"""
JWT 认证集成测试

覆盖 W0b-1a DoD：401 门禁、有效 token、refresh、admin 403。
"""

import jwt
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def enable_auth():
    """在本测试模块内启用 JWT 认证"""
    from app.config import config

    saved = {
        'enabled': config['auth']['enabled'],
        'secret': config['auth']['jwt_secret'],
    }
    config['auth']['enabled'] = True
    config['auth']['jwt_secret'] = 'test-jwt-secret-must-be-at-least-32-chars'
    yield
    config['auth']['enabled'] = saved['enabled']
    config['auth']['jwt_secret'] = saved['secret']


@pytest.fixture
async def auth_client(enable_auth):
    """启用认证后的测试客户端"""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        yield client


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    response = await client.post('/api/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()


def _auth_header(access_token: str) -> dict:
    return {'Authorization': f'Bearer {access_token}'}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_return_401_when_no_token(auth_client):
    """无 token 访问 /api/chat/sessions 应 401"""
    response = await auth_client.get('/api/chat/sessions')
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'UNAUTHORIZED'


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_allow_health_without_token(auth_client):
    """/health/live 无需认证"""
    response = await auth_client.get('/health/live')
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_access_api_with_valid_token(auth_client):
    """有效 access token 可访问 chat"""
    from unittest.mock import AsyncMock, patch

    tokens = await _login(auth_client, 'user', 'user123')
    with patch('app.routes.chat.list_sessions', new_callable=AsyncMock, return_value=[]):
        response = await auth_client.get('/api/chat/sessions', headers=_auth_header(tokens['accessToken']))
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_return_403_when_user_accesses_configs(auth_client):
    """user 角色访问 /api/configs 应 403"""
    tokens = await _login(auth_client, 'user', 'user123')
    response = await auth_client.get('/api/configs?type=prompt', headers=_auth_header(tokens['accessToken']))
    assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_return_403_when_user_accesses_admin_route(auth_client):
    """user 角色访问 /api/monitor/stats 应 403"""
    tokens = await _login(auth_client, 'user', 'user123')
    response = await auth_client.get('/api/monitor/stats', headers=_auth_header(tokens['accessToken']))
    assert response.status_code == 403
    body = response.json()
    assert body['detail']['error']['code'] == 'FORBIDDEN'


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_refresh_access_token(auth_client):
    """refresh token 可换取新 access token"""
    tokens = await _login(auth_client, 'admin', 'admin123')
    response = await auth_client.post(
        '/api/auth/refresh',
        json={'refreshToken': tokens['refreshToken']},
    )
    assert response.status_code == 200
    body = response.json()
    assert body['accessToken']
    assert body['refreshToken']
    assert body['role'] == 'admin'

    # 新 token 可用（mock DB）
    from unittest.mock import AsyncMock, patch

    with patch('app.routes.chat.list_sessions', new_callable=AsyncMock, return_value=[]):
        sessions = await auth_client.get('/api/chat/sessions', headers=_auth_header(body['accessToken']))
    assert sessions.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_return_401_when_access_token_expired(auth_client):
    """过期 access token 应 401"""
    from app.config import config

    secret = config['auth']['jwt_secret']
    expired = jwt.encode(
        {
            'sub': 'user',
            'username': 'user',
            'role': 'user',
            'type': 'access',
            'exp': 1,
            'iat': 1,
        },
        secret,
        algorithm='HS256',
    )
    response = await auth_client.get('/api/chat/sessions', headers=_auth_header(expired))
    assert response.status_code == 401
