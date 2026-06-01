> **最后核对日期**：2026-06-01 | **核对方式**：Context7 查官方文档
> **AI 库版本基准**：LangChain 1.0+ / LangGraph 1.0.8+
> **复核周期**：每季度（3/6/9/12 月）| **责任人**：维护者

# Agent 规范 — RAG 检索与向量库

> 本文件从 [agent.md](agent.md) 拆出，覆盖 RAG 检索增强和 VectorStore 设计规范。
>
> 与 [dba.md](dba.md)（PGVector 索引）/ [rag-evaluation.md](rag-evaluation.md)（评测）协同。

---

## 六、RAG 检索增强规范

### 6.1 文档切片（5 种策略，工厂模式）

| 策略 | 适用 | 实现 |
|------|------|------|
| **LENGTH** | 纯文本按字数 | `RecursiveCharacterTextSplitter` |
| **TITLE** | Markdown 按标题层级 | `MarkdownHeaderTextSplitter` |
| **SEMANTIC** | 按语义边界 | `SemanticChunker` |
| **PARENT_CHILD** | 保留父子关系 | `ParentDocumentRetriever` |
| **TABLE** | 表格 / Excel | 自定义 `TableAwareSplitter` |

✅ **正确示例**：

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.retrievers import ParentDocumentRetriever
from langchain.storage import InMemoryStore

# 父分段（保留完整语义）
parent_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)
# 子分段（用于检索，命中后回溯父分段）
child_splitter = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=50)

retriever = ParentDocumentRetriever(
    vectorstore=vectorstore,
    docstore=InMemoryStore(),
    child_splitter=child_splitter,
    parent_splitter=parent_splitter,
)
```

### 6.2 父子分段 / 兄弟分段

| 概念 | 必填字段 | 检索时行为 |
|------|---------|-----------|
| **parent_chunk_id** | ✅ 强制 | 命中子分段时回溯父分段完整文本 |
| **brother_chunk_id** | ✅ 强制 | 命中任一兄弟自动补全同级 |
| **skip_embedding** | 可选 | 父分段标记 `skip_embedding=1` 不参与向量检索 |

### 6.3 混合检索（BM25 + dense）

✅ **必须**使用 `EnsembleRetriever` 融合：

```python
from langchain.retrievers import BM25Retriever, EnsembleRetriever
from langchain_community.vectorstores import FAISS

bm25 = BM25Retriever.from_documents(docs)
bm25.k = 5
faiss = FAISS.from_documents(docs, embeddings).as_retriever(search_kwargs={"k": 5})

retriever = EnsembleRetriever(
    retrievers=[bm25, faiss],
    weights=[0.4, 0.6],  # 关键词 0.4，语义 0.6
)
```

❌ 禁止只用 dense（关键词命中差）；❌ 禁止只用 BM25（语义匹配差）。

### 6.4 Re-ranking

**强制**：向量检索后必须 Re-rank，否则 Top-K 质量不可控。

```python
from langchain_community.document_compressors import BgeRerank
from langchain.retrievers import ContextualCompressionRetriever

# ✅ 国产开源 BGE Reranker（零成本，本地部署）
compressor = BgeRerank(model="BAAI/bge-reranker-v2-m3", top_n=3)
retriever = ContextualCompressionRetriever(
    base_compressor=compressor,
    base_retriever=base_retriever,
)
```

> 备选方案：Qwen3-Reranker / BCE-reranker 等国产开源 Re-ranker，**禁止使用 Cohere Rerank / Jina Rerank 等国外服务**。

### 6.5 Query 改写

| 策略 | 适用 |
|------|------|
| **HyDE** | 短查询 / 概念抽象 |
| **Multi-Query** | 一查多角度 |
| **Step-Back** | 复杂问题先抽象再细化 |
| **Query Decompose** | 多跳问题拆子问题 |

✅ **必须**至少实现其中一种，无 Query 改写直接检索视为不合格。

### 6.6 引用溯源

**强制**：每个返回的 chunk 必须带 `source` / `score` / `metadata.doc_id` / `metadata.chunk_id`：

```python
from langchain_core.documents import Document

chunk = Document(
    page_content="...",
    metadata={
        "source": "user_manual_v3.pdf",
        "doc_id": "doc_abc123",
        "chunk_id": "chunk_xyz789",
        "score": 0.87,
        "page": 12,
    }
)
```

最终 answer 必须带 `[{n}]` 角标，引用编号对应 chunk 列表。

---

## 七、VectorStore 规范

### 7.1 索引选型决策树

```
Q: 数据规模？
├── < 100K 向量  → Chroma / PGVector
├── 100K-10M     → Qdrant / Milvus（standalone）
├── > 10M        → Milvus（cluster）
└── 已用 ES      → ES dense_vector

Q: 是否需要事务一致？
├── 是  → PGVector（与业务表同库）
└── 否  → 独立向量库

Q: 是否需要混合检索（BM25 + dense）？
├── 是  → ES / Milvus（内置）
└── 否  → 任意
```

### 7.2 元数据过滤（强制项）

每个 chunk 入库时 **必须** 携带以下元数据（用于权限 / 多租户 / 版本控制）：

```python
metadata = {
    "tenant_id": "tenant_001",        # 多租户隔离
    "accessible_by": ["user_1", "role_admin"],  # 权限
    "doc_id": "doc_xxx",
    "doc_version": "v3",              # 多版本
    "expire_date": "2026-12-31",      # 文档到期
    "source": "filename.pdf",
}
```

检索时 **必须** 注入 filter：

```python
results = vectorstore.similarity_search(
    query, k=5,
    filter={
        "tenant_id": current_user.tenant_id,
        "accessible_by": {"$in": [current_user.id, *current_user.roles]},
        "doc_version": "v3",
        "expire_date": {"$gte": today},
    }
)
```

### 7.3 权限过滤

❌ 禁止在应用层做权限过滤（检索后过滤）；**必须**在向量库层通过 metadata filter 实现，杜绝越权风险。

### 7.4 多版本管理

- 新版本发布后，旧版本 metadata 增加 `"deprecated": true`，**不删除**
- 检索时强制 filter `"deprecated": {"$ne": true}`
- 版本回滚：修改 filter 条件即可，**无需重新向量化**
