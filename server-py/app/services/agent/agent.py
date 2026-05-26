# ReAct Agent：LangGraph 实现
import json
from typing import Annotated

from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from typing_extensions import TypedDict

from ..model import create_chat_model
from .tools import all_tools
from ...utils.logger import logger


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
    messages: Annotated[list, add_messages]
    steps: int


agent_model = create_chat_model(temperature=0, streaming=True)
tool_node = ToolNode(all_tools)


async def agent_node(state: AgentState):
    response = await agent_model.bind_tools(all_tools).ainvoke([
        SystemMessage(AGENT_SYSTEM),
        *state['messages'],
    ])
    return {'messages': [response], 'steps': state.get('steps', 0) + 1}


def should_continue(state: AgentState):
    last = state['messages'][-1]
    if state.get('steps', 0) >= 8:
        logger.warn('agent: max steps reached', {'steps': state['steps']})
        return '__end__'
    return 'tools' if last.tool_calls else '__end__'


graph = StateGraph(AgentState)
graph.add_node('agent', agent_node)
graph.add_node('tools', tool_node)
graph.add_edge(START, 'agent')
graph.add_conditional_edges('agent', should_continue, {'tools': 'tools', '__end__': END})
graph.add_edge('tools', 'agent')
agent_graph = graph.compile()


def _get_tool_label(tool_name):
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
    logger.info('agent: start', {'task': task[:60]})
    step_count = 0

    try:
        async for event in agent_graph.astream_events(
            {'messages': [HumanMessage(task)], 'steps': 0},
            version='v2',
        ):
            event_type = event['event']
            name = event.get('name', '')
            data = event.get('data', {})

            if event_type == 'on_tool_start':
                step_count += 1
                await emit_event('tool_call', {
                    'step': step_count,
                    'toolName': name,
                    'args': data.get('input'),
                    'label': _get_tool_label(name),
                })

            if event_type == 'on_tool_end':
                result = data.get('output')
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

            if (event_type == 'on_chat_model_stream'
                    and data.get('chunk', {}).get('content')
                    and name == 'ChatOpenAI'):
                chunk = data['chunk']
                if not chunk.tool_call_chunks and chunk.content:
                    await emit_event('token', {'token': chunk.content})

        await emit_event('done', {'steps': step_count})
        logger.info('agent: done', {'steps': step_count})
    except Exception as err:
        logger.error('agent: error', {'error': str(err)})
        await emit_event('error', {'message': str(err) or 'Agent 执行出错'})


def get_tool_list():
    return [{
        'name': t.name,
        'label': _get_tool_label(t.name),
        'description': t.description,
    } for t in all_tools]
