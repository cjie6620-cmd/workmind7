"""Agent 副作用和 SSE 终态契约测试。"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.auth.models import UserContext
from app.routes.agent import _report_content_disposition, _resolve_agent_config, agent_run
from app.schemas.requests import AgentRunRequest
from app.services.agent.report_store import ReportStorageError, save_report
from app.services.agent.tools import calculate, send_notify
from app.services.agent.agent import _build_agent_graph, get_tool_list


class _ConnectedRequest:
    async def is_disconnected(self):
        return False


@pytest.mark.asyncio
async def test_unconfigured_notification_should_not_claim_success():
    raw = await send_notify.ainvoke(
        {
            "to": "user@example.com",
            "subject": "subject",
            "message": "message",
            "channel": "email",
        }
    )

    result = json.loads(raw)
    assert result["success"] is False
    assert result["code"] == "NOT_IMPLEMENTED"


@pytest.mark.asyncio
async def test_calculator_bounds_complexity_and_exponents():
    assert "计算结果" in await calculate.ainvoke({"expression": "1500 + 800 * 0.8"})
    assert "无效" in await calculate.ainvoke({"expression": "1 + os.system(2)"})
    assert "幂运算超出" in await calculate.ainvoke({"expression": "9 ** 999999"})


@pytest.mark.asyncio
async def test_report_storage_failure_should_raise():
    redis = MagicMock()
    redis.pipeline.return_value.execute.side_effect = RuntimeError("redis unavailable")

    with patch("app.services.agent.report_store.get_redis", return_value=redis):
        with pytest.raises(ReportStorageError):
            await save_report("title", "content", "user-1")


def test_report_download_header_should_be_a_valid_string():
    header = _report_content_disposition("月报")

    assert isinstance(header, str)
    assert "filename*=UTF-8" in header
    assert "%E6%9C%88%E6%8A%A5.md" in header


def test_agent_runtime_rejects_unknown_tools_before_execution():
    with pytest.raises(ValueError, match="未知工具"):
        _build_agent_graph(
            {
                "systemPrompt": "执行任务",
                "tools": ["not-a-tool"],
                "modelParams": {},
            }
        )


def test_unavailable_notification_is_not_bound_to_runtime_model():
    model = MagicMock()
    model.bind_tools.return_value = MagicMock()
    with patch("app.services.agent.agent.create_chat_model", return_value=model):
        _build_agent_graph(
            {
                "systemPrompt": "执行任务",
                "tools": ["calculate", "send_notify"],
                "modelParams": {},
            }
        )

    bound_tools = model.bind_tools.call_args.args[0]
    assert [tool.name for tool in bound_tools] == ["calculate"]
    catalog = {tool["name"]: tool for tool in get_tool_list()}
    assert catalog["send_notify"]["available"] is False


@pytest.mark.asyncio
async def test_agent_config_must_be_active_and_of_agent_type():
    with patch(
        "app.routes.agent.get_config",
        new=AsyncMock(
            return_value={
                "id": "cfg-1",
                "name": "停用配置",
                "configType": "agent",
                "configJson": {},
                "version": 1,
                "isActive": False,
            }
        ),
    ):
        with pytest.raises(RuntimeError, match="已停用"):
            await _resolve_agent_config("cfg-1")

    with patch(
        "app.routes.agent.get_config",
        new=AsyncMock(
            return_value={
                "id": "cfg-2",
                "name": "错误类型",
                "configType": "prompt",
                "configJson": {},
                "version": 1,
                "isActive": True,
            }
        ),
    ):
        with pytest.raises(LookupError, match="不存在"):
            await _resolve_agent_config("cfg-2")


@pytest.mark.asyncio
async def test_agent_error_should_not_be_followed_by_done():
    async def fail_agent(task, emit_event):
        raise RuntimeError("provider failed")

    request = AgentRunRequest(task="执行任务", sessionId="agent_user-1_test")
    user = UserContext(user_id="user-1", username="user", role="user")

    with (
        patch("app.routes.agent.assert_session_owner", new=AsyncMock()),
        patch("app.routes.agent.save_message", new=AsyncMock()),
        patch("app.routes.agent.run_agent", side_effect=fail_agent),
    ):
        response = await agent_run(request, _ConnectedRequest(), user)
        events = [event async for event in response.body_iterator]

    event_types = [event.event for event in events]
    assert "error" in event_types
    assert "done" not in event_types


@pytest.mark.asyncio
async def test_agent_success_should_emit_exactly_one_done_with_session_id():
    async def complete_agent(task, emit_event):
        await emit_event("token", {"token": "完成"})
        await emit_event("done", {"steps": 2, "finalAnswer": "完成"})

    request = AgentRunRequest(task="执行任务", sessionId="agent_user-1_test")
    user = UserContext(user_id="user-1", username="user", role="user")

    with (
        patch("app.routes.agent.assert_session_owner", new=AsyncMock()),
        patch("app.routes.agent.save_message", new=AsyncMock()),
        patch("app.routes.agent.run_agent", side_effect=complete_agent),
    ):
        response = await agent_run(request, _ConnectedRequest(), user)
        events = [event async for event in response.body_iterator]

    done_events = [event for event in events if event.event == "done"]
    assert len(done_events) == 1
    payload = json.loads(done_events[0].data)
    assert payload["sessionId"] == "agent_user-1_test"
    assert payload["steps"] == 2
