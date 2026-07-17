"""Chat 精确缓存上下文单元测试。"""

from app.services.cache import ExactCache, build_cache_context


def _context(**overrides):
    values = {
        "user_id": "user-a",
        "session_id": "session-a",
        "system_prompt": "system",
        "message": "继续",
        "history": [{"role": "user", "content": "上下文 A"}],
        "model_context": {"name": "deepseek-chat", "temperature": 0.7},
    }
    values.update(overrides)
    return build_cache_context(**values)


def test_cache_key_should_be_stable_for_equivalent_context():
    cache = ExactCache()
    first = _context(model_context={"name": "deepseek-chat", "temperature": 0.7})
    second = _context(model_context={"temperature": 0.7, "name": "deepseek-chat"})

    assert cache._key(first) == cache._key(second)


def test_cache_key_should_isolate_user_session_history_and_model():
    cache = ExactCache()
    keys = {
        cache._key(_context()),
        cache._key(_context(user_id="user-b")),
        cache._key(_context(session_id="session-b")),
        cache._key(_context(history=[{"role": "user", "content": "上下文 B"}])),
        cache._key(_context(model_context={"name": "other-model", "temperature": 0.7})),
    }

    assert len(keys) == 5
