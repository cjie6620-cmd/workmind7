"""
Agent 消息持久化集成测试
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
async def app_client():
    """创建 FastAPI 测试客户端"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        yield client


def _parse_sse_events(raw_text: str) -> list:
    """解析 SSE 原始文本为事件列表"""
    events = []
    current_event = None
    current_data = None

    for line in raw_text.replace('\r\n', '\n').split('\n'):
        if line.startswith('event:'):
            current_event = line[len('event:'):].strip()
        elif line.startswith('data:'):
            data_str = line[len('data:'):].strip()
            try:
                current_data = json.loads(data_str)
            except json.JSONDecodeError:
                current_data = data_str
        elif line == '' and current_event is not None:
            events.append({'event': current_event, 'data': current_data})
            current_event = None
            current_data = None

    return events


async def _mock_run_agent(task, emit_event):
    """模拟 Agent 流式输出 token"""
    await emit_event('token', {'token': 'Hello'})
    await emit_event('token', {'token': ' World'})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_persist_assistant_message_after_agent_run(app_client):
    """Agent 任务完成后应持久化 assistant 消息"""
    session_id = 'agent_dev_test_persist'
    saved_messages: list[tuple] = []

    async def capture_save(sid, role, content, **kwargs):
        saved_messages.append((sid, role, content))

    with patch('app.routes.agent.run_agent', side_effect=_mock_run_agent), \
         patch('app.routes.agent.save_message', side_effect=capture_save):
        response = await app_client.post(
            '/api/agent/run',
            json={'task': '测试任务', 'sessionId': session_id},
        )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert any(e['event'] == 'done' for e in events)

    # 等待后台 run_task 完成
    for _ in range(20):
        assistant_msgs = [m for m in saved_messages if m[1] == 'assistant']
        if assistant_msgs:
            break
        await asyncio.sleep(0.05)

    assistant_msgs = [m for m in saved_messages if m[1] == 'assistant']
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0][0] == session_id
    assert assistant_msgs[0][2] == 'Hello World'
