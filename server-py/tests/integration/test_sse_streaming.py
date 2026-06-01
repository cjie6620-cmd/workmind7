"""
SSE 流式集成测试

测试目标：app/routes/knowledge.py → rag_stream 端点的 SSE 事件流
覆盖：SSE 事件顺序、来源引用、流式 token

注意：标记为 @pytest.mark.integration，需要 FastAPI 应用可运行
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
async def app_client():
    """创建 FastAPI 测试客户端"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _parse_sse_events(raw_text: str) -> list:
    """解析 SSE 原始文本为事件列表"""
    events = []
    current_event = None
    current_data = None

    # SSE 标准使用 \r\n 分隔行，统一替换后再按 \n 分割
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


# ── SSE 流式响应测试 ──────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_stream_sse_events_in_correct_order(app_client):
    """SSE 事件应按 status → sources → token... → done 顺序"""
    mock_sources = [{
        'content': '年假5天',
        'title': '规章制度',
        'rerank_score': 0.95,
    }]

    async def mock_stream():
        yield '根据公司规定，年假5天。'

    mock_query_result = {
        'sources': mock_sources,
        'stream_answer': lambda: mock_stream(),
    }

    with patch('app.routes.knowledge.rag_query_stream', new_callable=AsyncMock,
               return_value=mock_query_result), \
         patch('app.routes.knowledge.save_message', new_callable=AsyncMock):
        response = await app_client.post(
            '/api/knowledge/query/stream',
            json={'question': '年假多少天'},
        )

    assert response.status_code == 200

    events = _parse_sse_events(response.text)
    event_types = [e['event'] for e in events]

    # 验证事件顺序
    assert 'status' in event_types
    assert 'sources' in event_types
    assert 'token' in event_types
    assert 'done' in event_types

    # status 应在 sources 之前
    assert event_types.index('status') < event_types.index('sources')
    # sources 应在 token 之前
    assert event_types.index('sources') < event_types.index('token')
    # done 应是最后一个事件
    assert event_types[-1] == 'done'


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_include_sources_in_sse(app_client):
    """SSE sources 事件应包含文档来源信息"""
    mock_sources = [{
        'content': '年假5天',
        'title': '规章制度',
        'rerank_score': 0.95,
    }]

    async def mock_stream():
        yield '年假5天。'

    mock_query_result = {
        'sources': mock_sources,
        'stream_answer': lambda: mock_stream(),
    }

    with patch('app.routes.knowledge.rag_query_stream', new_callable=AsyncMock,
               return_value=mock_query_result), \
         patch('app.routes.knowledge.save_message', new_callable=AsyncMock):
        response = await app_client.post(
            '/api/knowledge/query/stream',
            json={'question': '年假多少天'},
        )

    events = _parse_sse_events(response.text)
    sources_event = next((e for e in events if e['event'] == 'sources'), None)

    assert sources_event is not None
    assert 'sources' in sources_event['data']
    assert len(sources_event['data']['sources']) >= 1
    assert sources_event['data']['sources'][0]['title'] == '规章制度'


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_return_done_with_session_id(app_client):
    """SSE done 事件应包含 sessionId"""
    async def mock_stream():
        yield '回答内容。'

    mock_query_result = {
        'sources': [{'content': 'c', 'title': 't', 'rerank_score': 0.9}],
        'stream_answer': lambda: mock_stream(),
    }

    with patch('app.routes.knowledge.rag_query_stream', new_callable=AsyncMock,
               return_value=mock_query_result), \
         patch('app.routes.knowledge.save_message', new_callable=AsyncMock):
        response = await app_client.post(
            '/api/knowledge/query/stream',
            json={'question': '测试问题', 'sessionId': 'knowledge_test123'},
        )

    events = _parse_sse_events(response.text)
    done_event = next((e for e in events if e['event'] == 'done'), None)

    assert done_event is not None
    assert 'sessionId' in done_event['data']
    assert done_event['data']['sessionId'] == 'knowledge_test123'


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_handle_no_sources_gracefully(app_client):
    """无检索结果时应返回提示信息"""
    async def mock_stream():
        yield '未找到提示'

    mock_query_result = {
        'sources': [],
        'stream_answer': lambda: mock_stream(),
    }

    with patch('app.routes.knowledge.rag_query_stream', new_callable=AsyncMock,
               return_value=mock_query_result), \
         patch('app.routes.knowledge.save_message', new_callable=AsyncMock):
        response = await app_client.post(
            '/api/knowledge/query/stream',
            json={'question': '无关问题'},
        )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    event_types = [e['event'] for e in events]
    assert 'done' in event_types


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sse_auto_generates_session_id(app_client):
    """未提供 sessionId 时应自动生成"""
    async def mock_stream():
        yield '回答'

    mock_query_result = {
        'sources': [{'content': 'c', 'title': 't', 'rerank_score': 0.9}],
        'stream_answer': lambda: mock_stream(),
    }

    with patch('app.routes.knowledge.rag_query_stream', new_callable=AsyncMock,
               return_value=mock_query_result), \
         patch('app.routes.knowledge.save_message', new_callable=AsyncMock):
        response = await app_client.post(
            '/api/knowledge/query/stream',
            json={'question': '测试'},
        )

    events = _parse_sse_events(response.text)
    done_event = next((e for e in events if e['event'] == 'done'), None)

    assert done_event is not None
    session_id = done_event['data']['sessionId']
    assert session_id.startswith('knowledge_')
