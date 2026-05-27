"""
ReAct Agent 实现模块

基于 LangGraph 的任务 Agent：
- 采用 ReAct 模式（Reasoning + Acting）
- 支持工具调用（Tool Calling）
- 流式输出每个执行步骤
- 最多执行 8 步，防止无限循环

工作流程：
1. agent_node: 理解任务，决定是否调用工具
2. tools: 执行工具，获取结果
3. 循环直到任务完成
"""

from typing import Annotated

from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from typing_extensions import TypedDict

from ..model import create_chat_model
from .tools import all_tools
from ...utils.logger import logger

# Agent 系统提示词：定义角色、可用工具、工作原则
AGENT_SYSTEM = """你是 WorkMind AI 任务助手，专门处理办公场景的复杂任务。

可用工具：
- web_search：搜索最新技术资讯和信息
- read_doc：从公司知识库检索文档
- calculate：数学计算（金额、工期等）
- get_date：日期查询和计算
- write_report：生成并保存分析报告
- send_notify：发送通知给相关人员

工作原则：
1. 先理解任务的完整需求，想好需要哪些步骤
2. 按最少工具调用完成任务，避免重复查询
3. 获取到足够信息后立刻生成最终回答，不要继续无谓的工具调用
4. 回答要完整、准确，必要时生成报告

注意：
- 每次只调用一个工具，等结果回来再决定下一步
- 最多执行 8 步工具调用，超过后用已有信息给出最佳回答"""


class AgentState(TypedDict):
    """Agent 状态定义"""
    messages: Annotated[list, add_messages]  # 消息历史
    steps: int  # 已执行步数


# 创建 Agent 专用模型（温度 0，保持准确性，流式输出）
agent_model = create_chat_model(temperature=0, streaming=True)
# 工具节点：LangGraph 内置，处理工具调用
tool_node = ToolNode(all_tools)


async def agent_node(state: AgentState):
    """
    Agent 决策节点

    调用 LLM 分析任务，决定下一步行动：
    - 如果需要工具，LangGraph 自动路由到 tools 节点
    - 如果不需要，结束执行
    """
    response = await agent_model.bind_tools(all_tools).ainvoke([
        SystemMessage(AGENT_SYSTEM),
        *state['messages'],
    ])
    return {'messages': [response], 'steps': state.get('steps', 0) + 1}


def should_continue(state: AgentState):
    """
    条件边：判断是否继续执行工具

    终止条件：
    - 达到最大步数（8步）
    - LLM 不再调用工具
    """
    last = state['messages'][-1]
    if state.get('steps', 0) >= 8:
        logger.warn('agent: max steps reached', {'steps': state['steps']})
        return '__end__'
    return 'tools' if last.tool_calls else '__end__'


# 构建 Agent 图
graph = StateGraph(AgentState)
graph.add_node('agent', agent_node)          # 决策节点
graph.add_node('tools', tool_node)           # 工具执行节点
graph.add_edge(START, 'agent')               # 从 agent 开始
graph.add_conditional_edges('agent', should_continue, {'tools': 'tools', '__end__': END})
graph.add_edge('tools', 'agent')             # 工具执行完回到 agent
agent_graph = graph.compile()


def _get_tool_label(tool_name):
    """获取工具的中文标签"""
    labels = {
        'web_search': '联网搜索',
        'read_doc': '检索知识库',
        'calculate': '数学计算',
        'get_date': '日期查询',
        'write_report': '生成报告',
        'send_notify': '发送通知',
    }
    return labels.get(tool_name, tool_name)


async def run_agent(task, emit_event):
    """
    执行 Agent 任务

    参数：
    - task: 任务描述
    - emit_event: 事件回调函数，用于 SSE 推送

    SSE 事件：
    - tool_call: 工具调用开始
    - tool_result: 工具执行结果
    - token: 响应 token
    - done: 执行完成
    """
    logger.info('agent: start', {'task': task[:60]})
    step_count = 0

    try:
        # 使用 astream_events 监听执行过程
        async for event in agent_graph.astream_events(
            {'messages': [HumanMessage(task)], 'steps': 0},
            version='v2',
        ):
            event_type = event['event']
            name = event.get('name', '')
            data = event.get('data', {})

            # 工具调用开始
            if event_type == 'on_tool_start':
                step_count += 1
                await emit_event('tool_call', {
                    'step': step_count,
                    'toolName': name,
                    'args': data.get('input'),
                    'label': _get_tool_label(name),
                })

            # 工具调用完成
            if event_type == 'on_tool_end':
                result = data.get('output')
                # 尝试解析 JSON
                if isinstance(result, str):
                    try:
                        result = json.loads(result)
                    except (json.JSONDecodeError, ValueError):
                        pass
                await emit_event('tool_result', {
                    'toolName': name,
                    'result': result,
                    'resultText': result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                })

            # 流式 token 输出（LLM 响应部分）
            if (event_type == 'on_chat_model_stream'
                    and data.get('chunk', {}).get('content')
                    and name == 'ChatOpenAI'):
                chunk = data['chunk']
                # 排除 tool_call 相关的 chunk
                if not chunk.tool_call_chunks and chunk.content:
                    await emit_event('token', {'token': chunk.content})

        await emit_event('done', {'steps': step_count})
        logger.info('agent: done', {'steps': step_count})
    except Exception as err:
        logger.error('agent: error', {'error': str(err)})
        await emit_event('error', {'message': str(err) or 'Agent 执行出错'})


def get_tool_list():
    """获取所有可用工具列表"""
    return [{
        'name': t.name,
        'label': _get_tool_label(t.name),
        'description': t.description,
    } for t in all_tools]


import json  # 延迟导入，避免循环依赖