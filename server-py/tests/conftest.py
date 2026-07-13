"""
RAG 测试共享 fixtures

提供 mock 模型、测试数据库、golden dataset 加载等核心基础设施。
所有 mock 的 model_name 必须为 "deepseek-chat"，禁止 mock 为 gpt-4o / claude-*。
"""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import AsyncGenerator, List
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# 第一步：将 server-py 加入 sys.path，确保 import 正常
SERVER_PY = str(Path(__file__).resolve().parent.parent)
if SERVER_PY not in sys.path:
    sys.path.insert(0, SERVER_PY)

# 第二步：设置测试环境变量（必须在 import app 之前）
# 可通过 TEST_DATABASE_URL 覆盖；本地默认与 docker-compose 端口 5434 对齐
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-deepseek-key-for-testing')
os.environ.setdefault(
    'DATABASE_URL',
    os.environ.get(
        'TEST_DATABASE_URL',
        'postgresql+asyncpg://test:test@localhost:5434/workmind_test',
    ),
)
# 默认关闭认证，避免现有集成测试需携带 token；test_auth.py 内单独开启
os.environ.setdefault('AUTH_ENABLED', 'false')
os.environ.setdefault('JWT_SECRET', 'test-jwt-secret-must-be-at-least-32-chars')

FIXTURES_DIR = Path(__file__).parent / 'fixtures'
EMBEDDING_DIM = 1024


# ── 向量 Mock（hash 文本 → 1024 维确定向量）────────────────────

def _text_to_vector(text: str, dim: int = EMBEDDING_DIM) -> List[float]:
    """基于文本 hash 生成确定性向量，避免加载 2.2GB bge-m3"""
    seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**31)
    rng = np.random.RandomState(seed)
    vec = rng.randn(dim).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


class MockEmbeddings:
    """Mock 嵌入模型，替代 bge-m3（~2.2GB）"""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [_text_to_vector(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return _text_to_vector(text)

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> List[float]:
        return self.embed_query(text)


# ── Chat 模型 Mock（预设响应队列）──────────────────────────────

class MockChatModel:
    """
    Mock 对话模型，model_name 必须为 "deepseek-chat"

    支持 ainvoke（非流式）和 astream（流式）两种模式。
    """

    model_name = 'deepseek-chat'

    def __init__(self, responses: List[str] = None):
        self._responses = list(responses or ['这是一个模拟的回答。'])
        self._response_index = 0

    def set_responses(self, responses: List[str]):
        """设置响应队列"""
        self._responses = list(responses)
        self._response_index = 0

    async def ainvoke(self, messages, **kwargs):
        """非流式调用"""
        text = self._responses[self._response_index % len(self._responses)]
        self._response_index += 1
        result = MagicMock()
        result.content = text
        return result

    async def astream(self, messages, **kwargs):
        """流式调用：将响应拆分为单字符 chunk"""
        text = self._responses[self._response_index % len(self._responses)]
        self._response_index += 1
        for char in text:
            chunk = MagicMock()
            chunk.content = char
            yield chunk

    def pipe(self, other):
        """兼容 LangChain chain 语法 (prompt | model)"""
        chained = MagicMock()

        async def _ainvoke(inputs):
            return await self.ainvoke(None)

        async def _astream(inputs):
            async for chunk in self.astream(None):
                yield chunk

        chained.ainvoke = _ainvoke
        chained.astream = _astream
        return chained

    def __or__(self, other):
        """支持 prompt | model 语法"""
        return self.pipe(other)


# ── Reranker Mock（关键词重叠评分）─────────────────────────────

class MockReranker:
    """Mock CrossEncoder 重排器，避免加载 560MB 模型"""

    def __init__(self, threshold: float = 0.2):
        self.threshold = threshold

    def rerank(self, query: str, documents, top_n: int = 4) -> List[dict]:
        """基于关键词重叠的简化评分"""
        if not documents:
            return []

        query_words = set(query)
        scored = []
        for doc in documents:
            content = doc.page_content if hasattr(doc, 'page_content') else str(doc)
            content_words = set(content)
            overlap = len(query_words & content_words)
            score = min(overlap / max(len(query_words), 1), 1.0)
            scored.append((doc, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        results = []
        for doc, score in scored[:top_n]:
            if score < self.threshold:
                continue
            meta = doc.metadata if hasattr(doc, 'metadata') else {}
            results.append({
                'content': doc.page_content if hasattr(doc, 'page_content') else str(doc),
                'rerank_score': round(score, 4),
                'vector_score': meta.get('vector_score', 0),
                'title': meta.get('title', '未知来源'),
                'docId': meta.get('docId'),
                'category': meta.get('category'),
                'preview': (doc.page_content if hasattr(doc, 'page_content') else str(doc))[:80],
            })
        return results


# ── Fixtures ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singletons(request):
    """
    每个测试前重置所有模块级单例，防止状态泄漏

    重置对象：_chat_model, _embeddings, _reranker, _vector_store,
              _bm25_retriever, _bm25_stale, _doc_registry

    对 @pytest.mark.live 测试：清空单例为 None，让真实初始化逻辑执行（连接真实 DeepSeek API）
    对普通测试：注入 mock 对象（原有行为不变）
    """
    # 第一步：检测 live marker
    has_live = any(request.node.iter_markers("live"))

    import app.services.model as model_mod
    import app.services.rag.reranker as reranker_mod
    import app.services.rag.pgvector_store as store_mod
    import app.services.rag.hybrid_retriever as hybrid_mod
    import app.services.rag.ingest as ingest_mod

    # 第二步：保存原始值
    saved = {
        'model._chat_model': model_mod._chat_model,
        'model._embeddings': model_mod._embeddings,
        'reranker._reranker': reranker_mod._reranker,
        'store._vector_store': store_mod._vector_store,
        'hybrid._bm25_retriever': hybrid_mod._bm25_retriever,
        'hybrid._bm25_stale': hybrid_mod._bm25_stale,
        'ingest._doc_registry': dict(ingest_mod._doc_registry),
    }

    # 第三步：根据 live 标记决定注入策略
    if has_live:
        # live 模式：清空单例为 None，首次调用时触发真实初始化
        model_mod._chat_model = None
        model_mod._embeddings = None
        reranker_mod._reranker = None
        store_mod._vector_store = None
        hybrid_mod._bm25_retriever = None
        hybrid_mod._bm25_stale = True
        ingest_mod._doc_registry = {}
    else:
        # mock 模式：注入 mock 对象（原有逻辑）
        mock_embeddings = MockEmbeddings()
        mock_chat = MockChatModel()
        mock_reranker_instance = MockReranker()

        model_mod._chat_model = mock_chat
        model_mod._embeddings = mock_embeddings
        reranker_mod._reranker = mock_reranker_instance
        store_mod._vector_store = None
        hybrid_mod._bm25_retriever = None
        hybrid_mod._bm25_stale = True
        ingest_mod._doc_registry = {}

    yield

    # 第四步：恢复原始值
    model_mod._chat_model = saved['model._chat_model']
    model_mod._embeddings = saved['model._embeddings']
    reranker_mod._reranker = saved['reranker._reranker']
    store_mod._vector_store = saved['store._vector_store']
    hybrid_mod._bm25_retriever = saved['hybrid._bm25_retriever']
    hybrid_mod._bm25_stale = saved['hybrid._bm25_stale']
    ingest_mod._doc_registry = saved['ingest._doc_registry']


@pytest.fixture
def mock_embeddings():
    """获取 MockEmbeddings 实例"""
    from app.services import model as model_mod
    return model_mod._embeddings


@pytest.fixture
def mock_chat_model():
    """获取 MockChatModel 实例（可调用 set_responses 设置响应）"""
    from app.services import model as model_mod
    return model_mod._chat_model


@pytest.fixture
def mock_reranker():
    """获取 MockReranker 实例"""
    from app.services.rag import reranker as reranker_mod
    return reranker_mod._reranker


@pytest.fixture
def golden_dataset() -> List[dict]:
    """加载 golden dataset 评测数据集"""
    path = FIXTURES_DIR / 'golden_dataset.json'
    if not path.exists():
        pytest.skip('golden_dataset.json 不存在，跳过评测')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


@pytest.fixture
def expected_chunks() -> dict:
    """加载切片预期结果"""
    path = FIXTURES_DIR / 'expected_chunks.json'
    if not path.exists():
        pytest.skip('expected_chunks.json 不存在')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


@pytest.fixture
def sample_documents_dir() -> Path:
    """返回测试文档目录路径"""
    return FIXTURES_DIR / 'sample_documents'
