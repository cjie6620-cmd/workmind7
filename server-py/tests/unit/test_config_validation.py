"""配置中心与运行时注册表一致性测试。"""

import pytest

from app.config import config as runtime_config
from app.config import validate_config as validate_runtime_config
from app.services.config.validation import validate_config_payload


def test_runtime_config_rejects_invalid_business_timezone(monkeypatch):
    monkeypatch.setitem(runtime_config["app"], "business_timezone", "Mars/Olympus_Mons")

    with pytest.raises(SystemExit):
        validate_runtime_config()


def test_unknown_workflow_cannot_be_published():
    with pytest.raises(ValueError, match="没有已注册"):
        validate_config_payload("workflow", "invented_workflow", {})


def test_workflow_cannot_publish_fake_node_topology():
    with pytest.raises(ValueError, match="节点拓扑"):
        validate_config_payload(
            "workflow",
            "weekly_report",
            {
                "nodes": [{"id": "fake"}],
            },
        )


def test_agent_config_validates_tools_and_model_bounds():
    with pytest.raises(ValueError, match="未知工具"):
        validate_config_payload(
            "agent",
            "bad",
            {
                "systemPrompt": "hello",
                "tools": ["shell_everything"],
            },
        )

    with pytest.raises(ValueError, match="maxTokens"):
        validate_config_payload(
            "agent",
            "bad",
            {
                "systemPrompt": "hello",
                "tools": [],
                "modelParams": {"maxTokens": 100_000},
            },
        )

    with pytest.raises(ValueError, match="尚未接入"):
        validate_config_payload(
            "agent",
            "bad",
            {
                "systemPrompt": "hello",
                "tools": ["send_notify"],
            },
        )


def test_prompt_config_requires_non_empty_prompt():
    with pytest.raises(ValueError, match="不能为空"):
        validate_config_payload("prompt", "empty", {"systemPrompt": " "})
