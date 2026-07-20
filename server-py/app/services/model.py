"""
Model 模型工厂模块（对话模型与本地 Embeddings 的唯一创建入口）

- 所有对话模型都经 MonitoredChatOpenAI 包装（用量监控 + 预算护栏），
  业务层禁止直接实例化 ChatOpenAI
- langchain_openai 与 sentence_transformers(torch) 存在导入顺序相关的
  段错误风险，且 bge-m3 约 2.2GB 加载慢，因此统一延迟导入 + 延迟初始化；
  生产启动时由 lifespan 在线程池预加载

对外接口：
- get_chat_model(): 全局对话模型单例（temperature=0.7，流式）
- create_chat_model(): 按参数新建实例（Agent/Prompt 调试等需自定义参数的场景）
- get_embeddings(): 本地向量化模型单例
"""

import asyncio

from ..config import config


# ── 对话模型（延迟加载）──────────────────────────────────

_chat_model = None


def get_chat_model():
    """获取对话模型单例（首次调用时初始化，带监控拦截）"""
    global _chat_model
    if _chat_model is None:
        from .interceptor import MonitoredChatOpenAI

        _chat_model = MonitoredChatOpenAI(
            model=config["ai"]["primary_model"],
            api_key=config["ai"]["deepseek_key"],
            base_url=config["ai"]["base_url"],
            temperature=0.7,
            streaming=True,
            stream_usage=True,
            callbacks=[],
            timeout=config["ai"]["timeout_seconds"],
            max_retries=config["ai"]["max_retries"],
            max_tokens=config["ai"]["max_tokens"],
        )
    return _chat_model


def create_chat_model(temperature=0.7, streaming=False, callbacks=None, max_tokens=None):
    """创建新的 ChatOpenAI 模型实例（带监控拦截）"""
    from .interceptor import MonitoredChatOpenAI

    kwargs: dict = {
        "model": config["ai"]["primary_model"],
        "api_key": config["ai"]["deepseek_key"],
        "base_url": config["ai"]["base_url"],
        "temperature": temperature,
        "streaming": streaming,
        "stream_usage": True,
        "callbacks": callbacks or [],
        "timeout": config["ai"]["timeout_seconds"],
        "max_retries": config["ai"]["max_retries"],
    }
    kwargs["max_tokens"] = max_tokens if max_tokens is not None else config["ai"]["max_tokens"]
    return MonitoredChatOpenAI(**kwargs)


# ── 本地向量化模型封装 ──────────────────────────────────────


class _LocalEmbeddings:
    """
    基于 sentence-transformers 的本地 Embeddings 封装
    兼容 LangChain Embeddings 接口（embed_documents / embed_query / 异步版本）

    异步方法使用 asyncio.to_thread 在线程池中执行，避免阻塞 FastAPI 事件循环。
    """

    def __init__(self, model_path, device="cpu"):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_path, device=device)

    def embed_documents(self, texts):
        return self.model.encode(texts, normalize_embeddings=True).tolist()

    def embed_query(self, text):
        return self.model.encode([text], normalize_embeddings=True)[0].tolist()

    async def aembed_documents(self, texts):
        return await asyncio.to_thread(self.embed_documents, texts)

    async def aembed_query(self, text):
        return await asyncio.to_thread(self.embed_query, text)


# 向量化模型延迟加载（bge-m3 约 2.2GB，首次加载慢）
_embeddings = None


def get_embeddings():
    """获取向量化模型单例（延迟加载，首次调用时初始化）"""
    global _embeddings
    if _embeddings is None:
        model_path = config["ai"].get("embedding_model")
        if not model_path:
            raise RuntimeError("EMBEDDING_MODEL 未配置，无法初始化 embeddings")
        _embeddings = _LocalEmbeddings(
            model_path=model_path,
            device=config["ai"]["embedding_device"],
        )
    return _embeddings
