"""Health probes must not be rate-limited (Docker/K8s readiness)."""

from starlette.types import Scope

from app.middleware import StreamingSafeMiddleware


class _DummyApp:
    def __init__(self):
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True

        async def _send(message):
            return None

        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}", "more_body": False})


async def test_should_skip_rate_limit_for_health_ready(monkeypatch):
    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        return False

    monkeypatch.setattr("app.middleware._check_rate_limit", boom)
    app = _DummyApp()
    mw = StreamingSafeMiddleware(app)
    scope: Scope = {
        "type": "http",
        "path": "/health/ready",
        "method": "GET",
        "headers": [],
        "client": ("127.0.0.1", 12345),
    }
    messages = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        messages.append(message)

    await mw(scope, receive, send)
    assert app.called is True
    assert calls["n"] == 0
