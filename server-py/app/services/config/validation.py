"""配置中心发布前的运行时契约校验。"""


def validate_config_payload(config_type: str, name: str, config_json: dict) -> None:
    if not isinstance(config_json, dict):
        raise ValueError("configJson 必须是对象")

    if config_type == "workflow":
        from ..workflow.workflows import WORKFLOW_BUILDERS, WORKFLOW_META

        if name not in WORKFLOW_BUILDERS:
            raise ValueError(f"工作流「{name}」没有已注册的运行时实现")
        # 节点拓扑来自代码实现；配置中心只允许编辑展示元数据。
        if "nodes" in config_json:
            runtime_nodes = [node["id"] for node in WORKFLOW_META[name]["nodes"]]
            configured_nodes = [node.get("id") for node in config_json.get("nodes", []) if isinstance(node, dict)]
            if configured_nodes and configured_nodes != runtime_nodes:
                raise ValueError("工作流节点拓扑与已注册运行时实现不一致")
        return

    if config_type == "agent":
        from ..agent.tools import AVAILABLE_TOOL_NAMES, all_tools

        prompt = config_json.get("systemPrompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12_000:
            raise ValueError("Agent systemPrompt 不能为空且不能超过 12000 字")
        tools = config_json.get("tools", [])
        if not isinstance(tools, list) or not all(isinstance(item, str) for item in tools):
            raise ValueError("Agent tools 必须是字符串数组")
        supported = {tool.name for tool in all_tools}
        unknown = sorted(set(tools) - supported)
        if unknown:
            raise ValueError(f"Agent 配置包含未知工具：{', '.join(unknown)}")
        unavailable = sorted(set(tools) - AVAILABLE_TOOL_NAMES)
        if unavailable:
            raise ValueError(f"Agent 工具尚未接入：{', '.join(unavailable)}")
        params = config_json.get("modelParams") or {}
        temperature = params.get("temperature", 0)
        max_tokens = params.get("maxTokens", 2000)
        max_steps = params.get("maxSteps", 10)
        if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise ValueError("Agent temperature 必须在 0 到 2 之间")
        if not isinstance(max_tokens, int) or not 1 <= max_tokens <= 8000:
            raise ValueError("Agent maxTokens 必须在 1 到 8000 之间")
        if not isinstance(max_steps, int) or not 1 <= max_steps <= 10:
            raise ValueError("Agent maxSteps 必须在 1 到 10 之间")
        return

    if config_type == "prompt":
        prompt = config_json.get("systemPrompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
            raise ValueError("Prompt systemPrompt 不能为空且不能超过 8000 字")
        return

    raise ValueError(f"不支持的配置类型：{config_type}")
