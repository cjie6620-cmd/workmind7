"""
Agent 工具集模块

定义 Agent 可调用的 6 个工具：
1. web_search: 联网搜索技术资讯
2. read_doc: 检索知识库文档
3. calculate: 安全数学计算
4. get_date: 日期查询和计算
5. write_report: 生成分析报告
6. send_notify: 发送通知

每个工具使用 @tool 装饰器声明，
定义输入参数 schema（用于 LLM 理解如何调用）。
"""

import ast
import json
import operator
import math
from datetime import datetime, timedelta
from typing import Literal

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ..rag.query import retrieve_docs
from ...clients.tavily_client import format_search_response, get_tavily_client
from ...utils.business_time import business_now
from ...utils.logger import logger


# ── 工具1：联网搜索 ──────────────────────────────────────────


class SearchInput(BaseModel):
    """搜索工具输入参数"""

    query: str = Field(min_length=1, max_length=500, description="搜索关键词，尽量精确")


@tool(args_schema=SearchInput)
async def web_search(query: str) -> str:
    """
    搜索互联网获取最新技术资讯（Tavily）

    使用场景：
    - 了解某个技术的最新版本和特性
    - 查询不熟悉的知识点
    - 验证技术方案的可行性
    """
    logger.info("tool:search", {"query": query})

    client = get_tavily_client()
    if not client.is_configured:
        return f"搜索服务未配置，无法查询「{query}」。"

    try:
        data = await client.search(query)
        return format_search_response(data)
    except httpx.TimeoutException:
        logger.warn("tool:search timeout", {"query": query})
        return f"搜索「{query}」超时，请稍后重试。"
    except httpx.HTTPStatusError as e:
        logger.warn("tool:search http error", {"query": query, "status": e.response.status_code})
        return f"搜索服务暂时不可用（HTTP {e.response.status_code}），请稍后重试。"
    except Exception as e:
        logger.warn("tool:search failed", {"query": query, "error": str(e)})
        return f"搜索「{query}」失败：{e}"


# ── 工具2：读取知识库文档 ────────────────────────────────────


class ReadDocInput(BaseModel):
    """知识库查询输入参数"""

    question: str = Field(min_length=1, max_length=1000, description="要查询的问题或关键词")


@tool(args_schema=ReadDocInput)
async def read_doc(question: str) -> str:
    """
    从公司知识库检索文档内容

    使用场景：
    - 查询公司内部规定
    - 查阅产品手册
    - 获取技术文档
    """
    logger.info("tool:read_doc", {"question": question})
    try:
        from ...utils.agent_context import get_agent_user_id

        owner_user_id = get_agent_user_id()
        # fail-closed：无法确定归属用户时拒绝检索，避免退化为跨用户全库检索。
        if not owner_user_id:
            logger.warning("tool:read_doc missing user scope, refusing")
            return "无法确定用户身份，知识库检索已拒绝。"
        docs = await retrieve_docs(question, k=3, owner_user_id=owner_user_id, is_admin=False)
        if not docs:
            return f'知识库中未找到关于"{question}"的相关内容。'
        return "\n\n".join(f"[文档{i + 1}] {d['title']}：{d['content']}" for i, d in enumerate(docs))
    except Exception:
        return "知识库暂时不可用，请稍后重试。"


# ── 工具3：数学计算 ──────────────────────────────────────────


class CalculateInput(BaseModel):
    """计算工具输入参数"""

    expression: str = Field(min_length=1, max_length=256, description='数学表达式，如 "1500 + 800 * 0.8"')


# 安全支持的运算符
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.FloorDiv: operator.floordiv,
}


def _bounded_number(value):
    if not isinstance(value, (int, float)) or abs(value) > 1e18 or not math.isfinite(value):
        raise ValueError("计算结果超出允许范围")
    return value


def _safe_eval(node, depth=0):
    """
    安全求值：只允许基本数学运算，禁止任意代码执行

    通过 AST 解析，只允许以下节点类型：
    - Constant: 数字常量
    - BinOp: 二元运算（+ - * / % ** //）
    - UnaryOp: 一元运算（负数）
    """
    if depth > 20:
        raise ValueError("表达式嵌套过深")
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body, depth + 1)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return _bounded_number(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        left = _safe_eval(node.left, depth + 1)
        right = _safe_eval(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and (abs(right) > 12 or abs(left) > 1e9):
            raise ValueError("幂运算超出允许范围")
        return _bounded_number(_SAFE_OPS[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _bounded_number(_SAFE_OPS[type(node.op)](_safe_eval(node.operand, depth + 1)))
    raise ValueError("不支持的运算")


@tool(args_schema=CalculateInput)
async def calculate(expression: str) -> str:
    """
    执行数学计算

    支持：+ - * / % ** // 和括号
    使用 AST 安全解析，防止代码注入
    """
    logger.info("tool:calculate", {"expression": expression})
    try:
        if any(c not in "0123456789+-*/().% " for c in expression):
            return "无效的数学表达式"
        safe_expr = expression.strip()
        tree = ast.parse(safe_expr, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 64:
            raise ValueError("表达式过于复杂")
        result = _safe_eval(tree)
        return f"计算结果：{expression} = {result}"
    except Exception as e:
        return f"计算失败：{e}"


# ── 工具4：获取日期信息 ──────────────────────────────────────


class GetDateInput(BaseModel):
    """日期工具输入参数"""

    operation: Literal["today", "diff", "add_days"] = Field(description="日期操作")
    date1: str | None = Field(default=None, max_length=10, description="开始日期 YYYY-MM-DD")
    date2: str | None = Field(default=None, max_length=10, description="结束日期或天数")


@tool(args_schema=GetDateInput)
async def get_date(
    operation: str,
    date1: str | None = None,
    date2: str | None = None,
) -> str:
    """
    日期查询和计算

    支持操作：
    - today: 获取当前日期
    - diff: 计算两个日期之间的天数和工作日
    - add_days: 日期加减
    """
    logger.info("tool:get_date", {"operation": operation, "date1": date1, "date2": date2})
    now = business_now()
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]

    if operation == "today":
        return f"今天是 {now.year}年{now.month}月{now.day}日，星期{weekdays[now.weekday()]}"

    if operation == "diff" and date1 and date2:
        try:
            d1 = datetime.strptime(date1, "%Y-%m-%d")
            d2 = datetime.strptime(date2, "%Y-%m-%d")
            diff_days = abs((d2 - d1).days)
            if diff_days > 36_600:
                return "日期范围过大，最多支持 100 年"
            start = min(d1, d2)
            # 计算工作日（排除周末）
            workdays = sum(1 for i in range(diff_days + 1) if (start + timedelta(days=i)).weekday() < 5)
            return f"{date1} 到 {date2}：共 {diff_days} 天，其中工作日 {workdays} 天"
        except ValueError:
            return "日期格式不正确，请使用 YYYY-MM-DD 格式"

    if operation == "add_days" and date1 and date2:
        try:
            d = datetime.strptime(date1, "%Y-%m-%d")
            days = int(date2)
            if abs(days) > 36_600:
                return "日期偏移过大，最多支持 100 年"
            result = d + timedelta(days=days)
            return f"{date1} 加 {date2} 天后是 {result.strftime('%Y-%m-%d')}"
        except ValueError:
            return "日期格式不正确"

    return f"今天是 {now.strftime('%Y-%m-%d')}"


# ── 工具5：生成并保存报告 ────────────────────────────────────


class WriteReportInput(BaseModel):
    """报告生成输入参数"""

    title: str = Field(min_length=1, max_length=200, description="报告标题")
    content: str = Field(min_length=1, max_length=100_000, description="报告正文内容，使用 Markdown 格式")
    format: Literal["markdown"] = Field(default="markdown", description="输出格式")


@tool(args_schema=WriteReportInput)
async def write_report(title: str, content: str, format: str = "markdown") -> str:
    """
    生成结构化分析报告并保存

    输出格式：Markdown，包含标题、生成时间、正文、署名
    报告将保存到 Redis，可通过报告页面查看和下载
    """
    logger.info("tool:write_report", {"title": title, "format": format})
    timestamp = business_now().strftime("%Y-%m-%d %H:%M:%S %Z")
    report = f"# {title}\n\n> 生成时间：{timestamp}\n\n{content}\n\n---\n*由 Mr.Chen AI Agent 自动生成*"

    # 持久化成功后才允许向 Agent 声明报告已保存。
    from ...utils.agent_context import get_agent_user_id
    from .report_store import save_report

    user_id = get_agent_user_id()
    if not user_id:
        return json.dumps({"success": False, "message": "无法确定报告归属用户"}, ensure_ascii=False)

    meta = await save_report(title, report, user_id)

    return json.dumps(
        {
            "success": True,
            "reportId": meta["id"],
            "title": title,
            "content": report,
            "savedAt": timestamp,
            "message": f"报告「{title}」已生成并保存，共 {len(report)} 字",
        },
        ensure_ascii=False,
    )


# ── 工具6：发送通知 ──────────────────────────────────────────


class SendNotifyInput(BaseModel):
    """通知发送输入参数"""

    to: str = Field(min_length=1, max_length=200, description="接收人")
    subject: str = Field(min_length=1, max_length=200, description="消息主题")
    message: str = Field(min_length=1, max_length=5000, description="消息正文（简洁）")
    channel: Literal["email", "feishu", "dingtalk"] = Field(
        default="feishu", description="通知渠道: email/feishu/dingtalk"
    )


@tool(args_schema=SendNotifyInput)
async def send_notify(to: str, subject: str, message: str, channel: str = "feishu") -> str:
    """
    发送消息通知（MOCK - 模拟发送，不实际投递）

    支持渠道：
    - feishu: 飞书消息
    - email: 邮件
    - dingtalk: 钉钉消息
    """
    logger.warn("tool:send_notify unavailable", {"to": to, "subject": subject, "channel": channel})
    return json.dumps(
        {
            "success": False,
            "code": "NOT_IMPLEMENTED",
            "to": to,
            "subject": subject,
            "channel": channel,
            "message": f"{channel} 通知渠道尚未接入，消息未发送",
        },
        ensure_ascii=False,
    )


# 工具目录保留未接入项用于兼容旧配置和明确展示，但运行时只绑定已实现能力。
all_tools = [web_search, read_doc, calculate, get_date, write_report, send_notify]
AVAILABLE_TOOL_NAMES = frozenset(
    {
        "web_search",
        "read_doc",
        "calculate",
        "get_date",
        "write_report",
    }
)
