"""
向量存储单元测试

测试目标：app/services/rag/pgvector_store.py
覆盖：PGVectorStore 的 CRUD 操作和向量格式转换
"""

import pytest

from app.services.rag.pgvector_store import PGVectorStore


# ── 向量格式转换测试 ──────────────────────────────────────────

def test_vec_to_str_should_format_correctly():
    """_vec_to_str 应将向量转为 PostgreSQL 格式"""
    store = PGVectorStore()
    vec = [1.0, 2.5, -3.0]
    result = store._vec_to_str(vec)
    assert result == '[1.0,2.5,-3.0]'


def test_vec_to_str_should_handle_single_element():
    """单个元素向量应正确转换"""
    store = PGVectorStore()
    result = store._vec_to_str([0.5])
    assert result == '[0.5]'


def test_vec_to_str_should_handle_long_vector():
    """1024 维向量应正确转换"""
    store = PGVectorStore(embedding_dim=1024)
    vec = [0.1] * 1024
    result = store._vec_to_str(vec)
    assert result.startswith('[0.1')
    assert result.endswith('0.1]')
    assert result.count(',') == 1023


def test_should_initialize_with_correct_dimension():
    """应使用正确的向量维度初始化"""
    store = PGVectorStore(embedding_dim=1024)
    assert store.embedding_dim == 1024


def test_should_default_to_1024_dimension():
    """默认维度应为 1024"""
    store = PGVectorStore()
    assert store.embedding_dim == 1024


# ── Singleton 测试 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_vector_store_returns_singleton():
    """get_vector_store 应返回单例"""
    from app.services.rag import pgvector_store as mod

    # reset_singletons 已将 _vector_store 设为 None
    store1 = await mod.get_vector_store()
    store2 = await mod.get_vector_store()
    assert store1 is store2
    assert isinstance(store1, PGVectorStore)
