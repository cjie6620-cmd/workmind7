"""
ReAct Agent 实现模块

基于 LangGraph 的任务 Agent：
- 采用 ReAct 模式（Reasoning + Acting）
- 支持工具调用（Tool Calling）
- 流式输出每个执行步骤
- 最多执行 10 步，防止无限循环

工作流程：
1. agent_node: 理解任务，决定是否调用工具
2. tools: 执行工具，获取结果
3. 循环直到任务完成
"""

import json
import traceback
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

重要规则：
- 当任务要求生成报告、分析报告、总结报告时，必须调用 write_report 工具，不要在最终回答中直接输出报告全文
- 每次只调用一个工具，等结果回来再决定下一步
- 最多执行 10 步工具调用，超过后用已有信息给出最佳回答"""


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
    - 达到最大步数（10步）
    - LLM 不再调用工具
    """
    last = state['messages'][-1]
    if state.get('steps', 0) >= 10:
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
    - token: 响应 token（逐字流式）
    - done: 执行完成
    """
    logger.info('agent: start', {'task': task[:60]})
    step_count = 0
    final_answer = ''
    pending_tool_calls = {}  # 去重：同一个 tool_call 只 emit 一次
    last_report = None       # 记录最后一次报告元数据

    try:
        async for msg, metadata in agent_graph.astream(
            {'messages': [HumanMessage(task)], 'steps': 0},
            stream_mode='messages',
        ):
            node = metadata.get('langgraph_node', '')

            # agent 节点：AIMessageChunk（含 token 和 tool_call 信息）
            if node == 'agent':
                # 优先从 tool_call_chunks 取（流式场景），兜底从 tool_calls 取
                chunks = msg.tool_call_chunks or []
                calls = msg.tool_calls or []
                # 合并两个来源，按 id 去重
                all_tcs = []
                seen_ids = set()
                for tc in (chunks + calls):
                    tc_id = tc.get('id') or tc.get('name', '')
                    if tc_id and tc_id not in seen_ids:
                        seen_ids.add(tc_id)
                        all_tcs.append(tc)

                for tc in all_tcs:
                    tc_id = tc.get('id') or tc.get('name', '')
                    if tc.get('name') and tc_id not in pending_tool_calls:
                        pending_tool_calls[tc_id] = True
                        step_count += 1
                        logger.debug('agent: tool_call detected', {'step': step_count, 'tool': tc['name']})
                        await emit_event('tool_call', {
                            'step': step_count,
                            'toolName': tc['name'],
                            'args': tc.get('args'),
                            'label': _get_tool_label(tc['name']),
                        })

                # 流式 token（排除有工具调用的情况）
                has_tool_call = bool(all_tcs)
                if msg.content and not has_tool_call:
                    final_answer += msg.content
                    await emit_event('token', {'token': msg.content})

            # tools 节点：ToolMessage（完整工具结果）
            elif node == 'tools' and hasattr(msg, 'tool_call_id'):
                result = msg.content
                try:
                    result = json.loads(result)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
                tool_name = getattr(msg, 'name', '')
                logger.debug('agent: tool_result', {'tool': tool_name, 'is_dict': isinstance(result, dict)})
                tool_result_payload = {
                    'toolName': tool_name,
                    'result': result,
                    'resultText': result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                }
                # write_report 返回的报告数据单独提取，供前端展示卡片 + 下载
                if isinstance(result, dict) and result.get('reportId'):
                    last_report = {
                        'id': result['reportId'],
                        'title': result.get('title', ''),
                        'content': result.get('content', ''),
                    }
                    tool_result_payload['report'] = last_report
                    logger.info('agent: report extracted', {'id': result['reportId'], 'title': result.get('title', '')})
                await emit_event('tool_result', tool_result_payload)

        # done 事件附带报告元数据（二级保障）
        done_payload = {'steps': step_count, 'finalAnswer': final_answer}
        if last_report:
            done_payload['lastReport'] = last_report
        await emit_event('done', done_payload)
        logger.info('agent: done', {'steps': step_count, 'has_report': last_report is not None})
    except Exception as err:
        tb_str = traceback.format_exc()
        logger.error('agent: execution failed', {'error': str(err), 'traceback': tb_str})
        await emit_event('error', {'message': str(err), 'traceback': tb_str})


def get_tool_list():
    """获取所有可用工具列表"""
    return [{
        'name': t.name,
        'label': _get_tool_label(t.name),
        'description': t.description,
    } for t in all_tools]