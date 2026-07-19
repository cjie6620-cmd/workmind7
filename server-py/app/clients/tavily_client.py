"""
Tavily 搜索 API Client

封装 Tavily 联网搜索，供 Agent web_search 工具调用。
"""

import httpx

from ..config import config
from ..utils.logger import logger

TAVILY_SEARCH_URL = "https://api.tavily.com/search"

_client: "TavilyClient | None" = None


class TavilyClient:
    """Tavily 搜索 API 异步客户端"""

    def __init__(self) -> None:
        cfg = config.get("tavily", {})
        self._api_key: str = cfg.get("api_key", "")
        self._timeout: float = float(cfg.get("timeout", 30))
        self._max_results: int = int(cfg.get("max_results", 5))
        # 复用连接池，避免每次搜索新建/销毁 TCP+TLS 连接
        self._http: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        return self._http

    async def aclose(self) -> None:
        """关闭连接池（应用退出时调用）。"""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def search(self, query: str) -> dict:
        """
        执行联网搜索

        参数：
        - query: 搜索关键词

        返回：Tavily API 原始响应 dict
        """
        if not self._api_key:
            raise ValueError("TAVILY_API_KEY 未配置")

        payload = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": self._max_results,
            "include_answer": True,
        }

        logger.info("tavily:search", {"query": query, "max_results": self._max_results})

        resp = await self._get_http().post(TAVILY_SEARCH_URL, json=payload)
        resp.raise_for_status()
        return resp.json()


def format_search_response(data: dict) -> str:
    """将 Tavily 响应格式化为 Agent 可读的文本"""
    parts: list[str] = []

    answer = data.get("answer")
    if answer:
        parts.append(str(answer))

    results = data.get("results") or []
    if results:
        snippets = []
        for i, item in enumerate(results, 1):
            title = item.get("title", "")
            content = item.get("content", "")
            url = item.get("url", "")
            snippets.append(f"[{i}] {title}：{content}（{url}）")

        if parts:
            parts.append("参考资料：\n" + "\n".join(snippets))
        else:
            parts.append("\n".join(snippets))

    return "\n\n".join(parts) if parts else "未找到相关搜索结果。"


def get_tavily_client() -> TavilyClient:
    """获取 TavilyClient 单例"""
    global _client
    if _client is None:
        _client = TavilyClient()
    return _client


async def close_tavily_client() -> None:
    """关闭 TavilyClient 连接池（应用退出时调用）。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
