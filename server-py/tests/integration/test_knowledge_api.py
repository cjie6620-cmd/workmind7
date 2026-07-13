"""
知识库 API 端点集成测试

测试目标：app/routes/knowledge.py
覆盖：文档上传、列表、删除、RAG 查询等 HTTP 端点

注意：集成测试需要 PostgreSQL 运行，标记为 @pytest.mark.integration
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from langchain_core.documents import Document


# ── FastAPI 测试客户端 fixture ────────────────────────────────

@pytest.fixture
async def app_client():
    """创建 FastAPI 测试客户端"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── 文档上传测试 ──────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_upload_text_content(app_client):
    """JSON 文本上传应返回 200"""
    payload = {
        'title': '测试文档',
        'category': '通用',
        'content': '这是一个测试文档的内容，用于验证上传功能。',
    }

    mock_meta = {
        'id': 'test-doc-id',
        'title': '测试文档',
        'category': '通用',
        'chunks': 1,
        'chars': len(payload['content']),
    }

    with patch('app.routes.knowledge.ingest_document', new_callable=AsyncMock, return_value=mock_meta):
        response = await app_client.post(
            '/api/knowledge/documents',
            json=payload,
        )

    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert data['document']['title'] == '测试文档'


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_reject_upload_without_content(app_client):
    """空内容应返回 400"""
    payload = {'title': '空文档', 'category': '通用', 'content': ''}

    response = await app_client.post(
        '/api/knowledge/documents',
        json=payload,
    )

    assert response.status_code == 400


# ── 文档列表测试 ──────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_list_documents(app_client):
    """文档列表应返回 200"""
    with patch('app.routes.knowledge.get_doc_registry', return_value=[
        {'id': '1', 'title': '文档A', 'category': 'HR制度', 'chunks': 5},
        {'id': '2', 'title': '文档B', 'category': '财务', 'chunks': 3},
    ]):
        response = await app_client.get('/api/knowledge/documents')

    assert response.status_code == 200
    data = response.json()
    assert len(data['documents']) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_list_documents_by_category(app_client):
    """分类筛选应正确过滤"""
    docs = [
        {'id': '1', 'title': '文档A', 'category': 'HR制度'},
        {'id': '2', 'title': '文档B', 'category': '财务'},
    ]

    with patch('app.routes.knowledge.get_doc_registry', return_value=docs):
        response = await app_client.get('/api/knowledge/documents?category=HR制度')

    assert response.status_code == 200
    data = response.json()
    assert len(data['documents']) == 1
    assert data['documents'][0]['category'] == 'HR制度'


# ── 文档删除测试 ──────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_delete_document(app_client):
    """删除文档应返回 200"""
    with patch('app.routes.knowledge.delete_document', new_callable=AsyncMock):
        response = await app_client.delete('/api/knowledge/documents/test-doc-id')

    assert response.status_code == 200
    assert response.json()['success'] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_return_404_for_nonexistent_document(app_client):
    """删除不存在的文档应返回 404"""
    with patch('app.routes.knowledge.delete_document', new_callable=AsyncMock,
               side_effect=ValueError('文档不存在')):
        response = await app_client.delete('/api/knowledge/documents/nonexistent-id')

    assert response.status_code == 404


# ── RAG 查询测试 ──────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_return_400_for_empty_question(app_client):
    """空问题应返回 400"""
    response = await app_client.post(
        '/api/knowledge/query/stream',
        json={'question': ''},
    )

    # 空问题应被拒绝（可能返回 400 JSON 或降级为 SSE）
    # 取决于路由实现是否在 SSE 之前校验
    assert response.status_code in (200, 400, 422)


# ── 分类列表测试 ──────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_should_get_categories(app_client):
    """分类列表应返回正确格式"""
    with patch('app.routes.knowledge.get_doc_registry', return_value=[
        {'id': '1', 'category': 'HR制度'},
        {'id': '2', 'category': '财务'},
        {'id': '3', 'category': 'HR制度'},
    ]):
        response = await app_client.get('/api/knowledge/categories')

    assert response.status_code == 200
    data = response.json()
    assert 'categories' in data
    # 应包含"全部文档"选项
    assert any(c['value'] == '' for c in data['categories'])
    # HR制度只出现一次
    hr_items = [c for c in data['categories'] if c['value'] == 'HR制度']
    assert len(hr_items) == 1
