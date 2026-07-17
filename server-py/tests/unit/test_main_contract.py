"""应用兜底路由契约测试。"""

import json

import pytest

from app.main import catch_all
from app.routes import health


@pytest.mark.asyncio
async def test_unknown_api_route_should_return_404():
    response = await catch_all("api/not-found")

    assert response.status_code == 404
    assert json.loads(response.body)["error"]["message"].startswith("接口不存在")


@pytest.mark.asyncio
async def test_health_uptime_uses_monotonic_clock(monkeypatch):
    monkeypatch.setattr(health, "_start_time", 100.0)
    monkeypatch.setattr(health.time, "monotonic", lambda: 112.9)

    response = await health.health_live()

    assert response["uptime"] == 12
