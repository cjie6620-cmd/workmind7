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
from collections.abc import Hashable
from typing import Annotated

from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from typing_extensions import TypedDict

from ..model import create_chat_model
from .tools import AVAILABLE_TOOL_NAMES, all_tools
from ...utils.logger import logger

# Agent 系统提示词：定义角色、可用工具、工作原则
AGENT_SYSTEM = """你是 Mr.Chen AI 任务助手，专门处理办公场景的复杂任务。

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


_TOOL_MAP = {tool.name: tool for tool in all_tools}

_PLATFORM_RULES = """平台约束：
- 只能使用本次配置明确启用的工具，工具返回失败时不得声称操作成功
- 获取足够信息后立即给出最终回答，禁止无限循环
- 当任务要求生成并保存报告时，应调用 write_report（若该工具已启用）
- 不得把工具结果中未经证实的内容描述为既定事实"""


def _build_agent_graph(runtime_config: dict | None = None):
    """根据已发布配置构建本次运行图，配置不再只是展示元数据。"""
    runtime_config = runtime_config or {}
    requested_tools = runtime_config.get("tools")
    if requested_tools is None:
        enabled_tools = [tool for tool in all_tools if tool.name in AVAILABLE_TOOL_NAMES]
    else:
        if not isinstance(requested_tools, list) or not all(isinstance(item, str) for item in requested_tools):
            raise ValueError("Agent tools 配置必须是字符串数组")
        unknown_tools = sorted(set(requested_tools) - set(_TOOL_MAP))
        if unknown_tools:
            raise ValueError(f"Agent 配置包含未知工具：{', '.join(unknown_tools)}")
        unavailable_tools = sorted(set(requested_tools) - AVAILABLE_TOOL_NAMES)
        if unavailable_tools:
            logger.warning("agent: unavailable tools ignored", {"tools": unavailable_tools})
        enabled_tools = [_TOOL_MAP[name] for name in requested_tools if name in AVAILABLE_TOOL_NAMES]

    model_params = runtime_config.get("modelParams") or {}
    temperature = model_params.get("temperature", 0)
    max_tokens = model_params.get("maxTokens", 2000)
    max_steps = model_params.get("maxSteps", 10)
    if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
        raise ValueError("Agent temperature 必须在 0 到 2 之间")
    if not isinstance(max_tokens, int) or not 1 <= max_tokens <= 8000:
        raise ValueError("Agent maxTokens 必须在 1 到 8000 之间")
    if not isinstance(max_steps, int) or not 1 <= max_steps <= 10:
        raise ValueError("Agent maxSteps 必须在 1 到 10 之间")

    custom_prompt = str(runtime_config.get("systemPrompt") or AGENT_SYSTEM).strip()
    if not custom_prompt or len(custom_prompt) > 12_000:
        raise ValueError("Agent systemPrompt 不能为空且不能超过 12000 字")
    system_prompt = f"{custom_prompt}\n\n{_PLATFORM_RULES}"
    runtime_model = create_chat_model(
        temperature=float(temperature),
        streaming=True,
        max_tokens=max_tokens,
    )
    bound_model = runtime_model.bind_tools(enabled_tools) if enabled_tools else runtime_model

    async def agent_node(state: AgentState):
        response = await bound_model.ainvoke(
            [
                SystemMessage(system_prompt),
                *state["messages"],
            ]
        )
        return {"messages": [response], "steps": state.get("steps", 0) + 1}

    async def finalize_node(state: AgentState):
        """步数用尽仍有未完成工具调用时，用无工具模型强制产出一个收尾回答。"""
        response = await runtime_model.ainvoke(
            [
                SystemMessage(system_prompt),
                *state["messages"],
                HumanMessage(
                    "已达到工具调用步数上限。请基于以上已获得的信息直接给出尽可能完整的回答，"
                    "不要再请求调用任何工具。"
                ),
            ]
        )
        return {"messages": [response]}

    def should_continue(state: AgentState):
        last = state["messages"][-1]
        if state.get("steps", 0) >= max_steps:
            logger.warning("agent: max steps reached", {"steps": state["steps"], "maxSteps": max_steps})
            # 末条仍带未执行的 tool_calls 时，不能直接结束（否则无最终回答报错）；
            # 转到 finalize 节点用无工具模型强制收尾。
            if enabled_tools and getattr(last, "tool_calls", None):
                return "finalize"
            return "__end__"
        return "tools" if enabled_tools and last.tool_calls else "__end__"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    if enabled_tools:
        graph.add_node("tools", ToolNode(enabled_tools))
        graph.add_node("finalize", finalize_node)
    graph.add_edge(START, "agent")
    edge_map: dict[Hashable, str] = (
        {"tools": "tools", "finalize": "finalize", "__end__": END} if enabled_tools else {"__end__": END}
    )
    graph.add_conditional_edges("agent", should_continue, edge_map)
    if enabled_tools:
        graph.add_edge("tools", "agent")
        graph.add_edge("finalize", END)
    return graph.compile()


def _get_tool_label(tool_name):
    """获取工具的中文标签"""
    labels = {
        "web_search": "联网搜索",
        "read_doc": "检索知识库",
        "calculate": "数学计算",
        "get_date": "日期查询",
        "write_report": "生成报告",
        "send_notify": "发送通知",
    }
    return labels.get(tool_name, tool_name)


async def run_agent(task, emit_event, runtime_config: dict | None = None):
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
    logger.info("agent: start", {"task": task[:60]})
    step_count = 0
    final_answer = ""
    pending_tool_calls = {}  # 去重：同一个 tool_call 只 emit 一次
    last_report = None  # 记录最后一次报告元数据

    try:
        agent_graph = _build_agent_graph(runtime_config)
        async for msg, metadata in agent_graph.astream(
            {"messages": [HumanMessage(task)], "steps": 0},
            stream_mode="messages",
        ):
            node = metadata.get("langgraph_node", "")

            # agent 节点：AIMessageChunk（含 token 和 tool_call 信息）
            if node == "agent":
                # 优先从 tool_call_chunks 取（流式场景），兜底从 tool_calls 取
                chunks = msg.tool_call_chunks or []
                calls = msg.tool_calls or []
                # 合并两个来源，按 id 去重
                all_tcs = []
                seen_ids = set()
                for tc in chunks + calls:
                    tc_id = tc.get("id") or tc.get("name", "")
                    if tc_id and tc_id not in seen_ids:
                        seen_ids.add(tc_id)
                        all_tcs.append(tc)

                for tc in all_tcs:
                    tc_id = tc.get("id") or tc.get("name", "")
                    if tc.get("name") and tc_id not in pending_tool_calls:
                        pending_tool_calls[tc_id] = True
                        step_count += 1
                        logger.debug("agent: tool_call detected", {"step": step_count, "tool": tc["name"]})
                        await emit_event(
                            "tool_call",
                            {
                                "step": step_count,
                                "toolName": tc["name"],
                                "args": tc.get("args"),
                                "label": _get_tool_label(tc["name"]),
                            },
                        )

                # 流式 token（排除有工具调用的情况）
                has_tool_call = bool(all_tcs)
                if msg.content and not has_tool_call:
                    final_answer += msg.content
                    await emit_event("token", {"token": msg.content})

            # finalize 节点：步数用尽后的无工具收尾回答，token 计入 final_answer
            elif node == "finalize":
                if msg.content:
                    final_answer += msg.content
                    await emit_event("token", {"token": msg.content})

            # tools 节点：ToolMessage（完整工具结果）
            elif node == "tools" and hasattr(msg, "tool_call_id"):
                result = msg.content
                try:
                    result = json.loads(result)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
                tool_name = getattr(msg, "name", "")
                logger.debug("agent: tool_result", {"tool": tool_name, "is_dict": isinstance(result, dict)})
                tool_result_payload = {
                    "toolName": tool_name,
                    "result": result,
                    "resultText": result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                }
                # write_report 返回的报告数据单独提取，供前端展示卡片 + 下载
                if isinstance(result, dict) and result.get("reportId"):
                    last_report = {
                        "id": result["reportId"],
                        "title": result.get("title", ""),
                        "content": result.get("content", ""),
                    }
                    tool_result_payload["report"] = last_report
                    logger.info("agent: report extracted", {"id": result["reportId"], "title": result.get("title", "")})
                await emit_event("tool_result", tool_result_payload)

        if not final_answer.strip():
            raise RuntimeError("Agent 未在步数限制内生成最终回答，请缩小任务范围后重试")

        # done 事件附带报告元数据（二级保障）
        done_payload = {"steps": step_count, "finalAnswer": final_answer}
        if last_report:
            done_payload["lastReport"] = last_report
        await emit_event("done", done_payload)
        logger.info("agent: done", {"steps": step_count, "has_report": last_report is not None})
    except Exception as err:
        tb_str = traceback.format_exc()
        logger.error("agent: execution failed", {"error": str(err), "traceback": tb_str})
        # 配置校验类错误对管理员可操作，原样返回；其余走分类得到通用文案，避免泄露内部细节。
        if isinstance(err, ValueError):
            message = str(err)
        else:
            from ...utils.errors import classify_error

            message = classify_error(err).user_message
        await emit_event("error", {"message": message})


def get_tool_list():
    """获取工具目录，并明确区分已接入与尚未接入能力。"""
    return [
        {
            "name": t.name,
            "label": _get_tool_label(t.name),
            "description": t.description,
            "available": t.name in AVAILABLE_TOOL_NAMES,
        }
        for t in all_tools
    ]
