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
from datetime import datetime, timedelta

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ..rag.query import retrieve_docs
from ...utils.logger import logger


# ── 工具1：联网搜索 ──────────────────────────────────────────

class SearchInput(BaseModel):
    """搜索工具输入参数"""
    query: str = Field(description='搜索关键词，尽量精确')


@tool(args_schema=SearchInput)
async def web_search(query: str) -> str:
    """
    搜索互联网获取最新技术资讯（MOCK - 返回预置结果）

    使用场景：
    - 了解某个技术的最新版本和特性
    - 查询不熟悉的知识点
    - 验证技术方案的可行性
    """
    logger.info('tool:search', {'query': query})

    # TODO: 接入真实搜索 API（SearXNG / Bing Web Search / Tavily）
    mock_results = {
        'Vue3': 'Vue 3.4.21 是目前最新版本，于2024年3月发布。主要改进：defineModel() 正式稳定，响应式系统性能提升约 56%。',
        'React': 'React 18.3 是最新稳定版，引入了并发渲染、useTransition、Suspense 改进。',
        'Vite': 'Vite 5.2 是目前最新版本，使用 Rollup 4 构建，冷启动速度提升 30%。',
        'DeepSeek': 'DeepSeek-V3 于2024年12月发布，是目前最强的开源 LLM 之一，中文表现优秀。',
        'TypeScript': 'TypeScript 5.7 是最新版本，新增 noUncheckedSideEffectImports 选项。',
        '微前端': 'qiankun 2.x 和 wujie 是国内最流行的微前端框架。',
    }

    # 模糊匹配
    for key, val in mock_results.items():
        if key.lower() in query.lower():
            return val
    return f'关于"{query}"的搜索结果：该话题在技术社区有广泛讨论。建议查阅官方文档获取最准确的信息。'


# ── 工具2：读取知识库文档 ────────────────────────────────────

class ReadDocInput(BaseModel):
    """知识库查询输入参数"""
    question: str = Field(description='要查询的问题或关键词')


@tool(args_schema=ReadDocInput)
async def read_doc(question: str) -> str:
    """
    从公司知识库检索文档内容

    使用场景：
    - 查询公司内部规定
    - 查阅产品手册
    - 获取技术文档
    """
    logger.info('tool:read_doc', {'question': question})
    try:
        docs = await retrieve_docs(question, k=3)
        if not docs:
            return f'知识库中未找到关于"{question}"的相关内容。'
        return '\n\n'.join(f'[文档{i + 1}] {d["title"]}：{d["content"]}' for i, d in enumerate(docs))
    except Exception:
        return '知识库暂时不可用，请稍后重试。'


# ── 工具3：数学计算 ──────────────────────────────────────────

class CalculateInput(BaseModel):
    """计算工具输入参数"""
    expression: str = Field(description='数学表达式，如 "1500 + 800 * 0.8"')


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


def _safe_eval(node):
    """
    安全求值：只允许基本数学运算，禁止任意代码执行

    通过 AST 解析，只允许以下节点类型：
    - Constant: 数字常量
    - BinOp: 二元运算（+ - * / % ** //）
    - UnaryOp: 一元运算（负数）
    """
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError('不支持的运算')


@tool(args_schema=CalculateInput)
async def calculate(expression: str) -> str:
    """
    执行数学计算

    支持：+ - * / % ** // 和括号
    使用 AST 安全解析，防止代码注入
    """
    logger.info('tool:calculate', {'expression': expression})
    try:
        # 过滤只保留数字和运算符
        safe_expr = ''.join(c for c in expression if c in '0123456789+-*/().% ').strip()
        if not safe_expr:
            return '无效的数学表达式'
        tree = ast.parse(safe_expr, mode='eval')
        result = _safe_eval(tree)
        return f'计算结果：{expression} = {result}'
    except Exception as e:
        return f'计算失败：{e}'


# ── 工具4：获取日期信息 ──────────────────────────────────────

class GetDateInput(BaseModel):
    """日期工具输入参数"""
    operation: str = Field(description='today=获取今天日期, diff=计算日期差, add_days=日期加减')
    date1: str = Field(default=None, description='开始日期 YYYY-MM-DD')
    date2: str = Field(default=None, description='结束日期或天数')


@tool(args_schema=GetDateInput)
async def get_date(operation: str, date1: str = None, date2: str = None) -> str:
    """
    日期查询和计算

    支持操作：
    - today: 获取当前日期
    - diff: 计算两个日期之间的天数和工作日
    - add_days: 日期加减
    """
    logger.info('tool:get_date', {'operation': operation, 'date1': date1, 'date2': date2})
    now = datetime.now()
    weekdays = ['一', '二', '三', '四', '五', '六', '日']

    if operation == 'today':
        return f'今天是 {now.year}年{now.month}月{now.day}日，星期{weekdays[now.weekday()]}'

    if operation == 'diff' and date1 and date2:
        try:
            d1 = datetime.strptime(date1, '%Y-%m-%d')
            d2 = datetime.strptime(date2, '%Y-%m-%d')
            diff_days = abs((d2 - d1).days)
            start, end = min(d1, d2), max(d1, d2)
            # 计算工作日（排除周末）
            workdays = sum(1 for i in range(diff_days + 1)
                          if (start + timedelta(days=i)).weekday() < 5)
            return f'{date1} 到 {date2}：共 {diff_days} 天，其中工作日 {workdays} 天'
        except ValueError:
            return '日期格式不正确，请使用 YYYY-MM-DD 格式'

    if operation == 'add_days' and date1 and date2:
        try:
            d = datetime.strptime(date1, '%Y-%m-%d')
            result = d + timedelta(days=int(date2))
            return f'{date1} 加 {date2} 天后是 {result.strftime("%Y-%m-%d")}'
        except ValueError:
            return '日期格式不正确'

    return f'今天是 {now.strftime("%Y-%m-%d")}'


# ── 工具5：生成并保存报告 ────────────────────────────────────

class WriteReportInput(BaseModel):
    """报告生成输入参数"""
    title: str = Field(description='报告标题')
    content: str = Field(description='报告正文内容，使用 Markdown 格式')
    format: str = Field(default='markdown', description='输出格式')


@tool(args_schema=WriteReportInput)
async def write_report(title: str, content: str, format: str = 'markdown') -> str:
    """
    生成结构化分析报告并保存

    输出格式：Markdown，包含标题、生成时间、正文、署名
    报告将保存到 Redis，可通过报告页面查看和下载
    """
    logger.info('tool:write_report', {'title': title, 'format': format})
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    report = f'# {title}\n\n> 生成时间：{timestamp}\n\n{content}\n\n---\n*由 WorkMind AI Agent 自动生成*'

    # 持久化保存（Redis 不可用时仅影响列表查询，不影响工具返回）
    from .report_store import save_report
    meta = save_report(title, report)

    return json.dumps({
        'success': True,
        'reportId': meta['id'],
        'title': title,
        'content': report,
        'savedAt': timestamp,
        'message': f'报告「{title}」已生成并保存，共 {len(report)} 字',
    }, ensure_ascii=False)


# ── 工具6：发送通知 ──────────────────────────────────────────

class SendNotifyInput(BaseModel):
    """通知发送输入参数"""
    to: str = Field(description='接收人')
    subject: str = Field(description='消息主题')
    message: str = Field(description='消息正文（简洁）')
    channel: str = Field(default='feishu', description='通知渠道: email/feishu/dingtalk')


@tool(args_schema=SendNotifyInput)
async def send_notify(to: str, subject: str, message: str, channel: str = 'feishu') -> str:
    """
    发送消息通知（MOCK - 模拟发送，不实际投递）

    支持渠道：
    - feishu: 飞书消息
    - email: 邮件
    - dingtalk: 钉钉消息
    """
    logger.info('tool:send_notify', {'to': to, 'subject': subject, 'channel': channel})
    # TODO: 接入实际通知渠道 SDK
    import asyncio
    await asyncio.sleep(0.2)  # 模拟网络延迟
    return json.dumps({
        'success': True,
        'to': to,
        'subject': subject,
        'channel': channel,
        'sentAt': datetime.now().isoformat(),
        'message': f'通知已通过 {channel} 发送给 {to}',
    }, ensure_ascii=False)


# 导出所有工具（Agent 初始化时使用）
all_tools = [web_search, read_doc, calculate, get_date, write_report, send_notify]