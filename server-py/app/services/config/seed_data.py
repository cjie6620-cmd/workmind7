"""
配置种子数据

服务首次启动时自动填充，仅当对应类型的配置为空时才插入。
"""

# ── Prompt 模板种子 ──────────────────────────────────────────

PROMPT_SEEDS = [
    {
        "name": "前端助手",
        "config_json": {
            "systemPrompt": "你是前端开发专家，精通 Vue3、React、TypeScript。回答简洁准确，必要时给代码示例。",
            "description": "通用前端技术问答",
            "tags": ["前端", "技术"],
            "versions": [],
        },
    },
    {
        "name": "代码 Review",
        "config_json": {
            "systemPrompt": (
                "你是资深代码评审专家。审查代码时，按以下顺序输出：\n"
                "1. 【总体评价】一句话概括\n"
                "2. 【问题列表】按严重程度排序，每条格式：[严重/一般/建议] 具体问题\n"
                "3. 【优化建议】具体的改进代码示例\n"
                "语气专业，直指问题，不废话。"
            ),
            "description": "代码审查专用",
            "tags": ["代码", "审查"],
            "versions": [],
        },
    },
    {
        "name": "简洁问答",
        "config_json": {
            "systemPrompt": "用最简洁的语言回答问题，不超过3句话，不用废话开场。",
            "description": "简短精准的回答风格",
            "tags": ["简洁"],
            "versions": [],
        },
    },
]

# ── Agent 配置种子 ──────────────────────────────────────────

AGENT_SEEDS = [
    {
        "name": "默认任务 Agent",
        "config_json": {
            "systemPrompt": (
                "你是一个智能任务执行 Agent。根据用户任务描述，自动规划执行步骤，"
                "调用合适的工具完成任务。每次只调用一个工具，根据结果决定下一步。"
            ),
            "description": "默认任务执行 Agent，包含当前已接入工具",
            "tools": ["web_search", "read_doc", "calculate", "get_date", "write_report"],
            "modelParams": {
                "temperature": 0.7,
                "maxTokens": 2000,
            },
        },
    },
]

# ── Workflow 配置种子 ────────────────────────────────────────

WORKFLOW_SEEDS = [
    {
        "name": "weekly_report",
        "config_json": {
            "title": "周报生成",
            "icon": "📊",
            "description": "输入本周工作要点，自动提炼亮点、识别风险，生成规范周报",
            "inputLabel": "本周工作要点",
            "inputPlaceholder": "请简单描述本周完成的主要工作，一条一行...",
            "extraField": {"key": "dept", "label": "部门名称", "placeholder": "如：前端研发组"},
            "nodes": [
                {"id": "extract_highlights", "label": "提炼工作亮点"},
                {"id": "identify_risks", "label": "识别风险阻塞"},
                {"id": "human_review", "label": "人工审核", "isHuman": True},
                {"id": "generate_report", "label": "生成周报"},
            ],
            "resultKey": "report",
        },
    },
    {
        "name": "meeting_minutes",
        "config_json": {
            "title": "会议纪要",
            "icon": "📝",
            "description": "粘贴会议原始记录，自动提取结论和 Action Items，生成正式纪要",
            "inputLabel": "会议原始记录",
            "inputPlaceholder": "粘贴会议记录，包括讨论内容、发言摘要等...",
            "extraField": {"key": "meetingTitle", "label": "会议名称", "placeholder": "如：产品周会 2024-03"},
            "nodes": [
                {"id": "extract_attendees", "label": "提取参会人与议题"},
                {"id": "extract_conclusions", "label": "提取会议结论"},
                {"id": "extract_actions", "label": "整理 Action Items"},
                {"id": "human_review", "label": "人工审核", "isHuman": True},
                {"id": "generate_minutes", "label": "生成纪要"},
            ],
            "resultKey": "minutes",
        },
    },
    {
        "name": "email_polish",
        "config_json": {
            "title": "邮件润色",
            "icon": "✉️",
            "description": "输入邮件草稿，AI 分析语气和问题，润色成正式邮件",
            "inputLabel": "邮件草稿",
            "inputPlaceholder": "粘贴你的邮件草稿...",
            "extraField": {"key": "recipient", "label": "收件人/场景", "placeholder": "如：客户、上级、合作方"},
            "nodes": [
                {"id": "analyze_intent", "label": "分析写作意图"},
                {"id": "check_issues", "label": "检查问题"},
                {"id": "human_review", "label": "人工审核", "isHuman": True},
                {"id": "polish_email", "label": "生成润色版本"},
            ],
            "resultKey": "polished",
        },
    },
    {
        "name": "prd_skeleton",
        "config_json": {
            "title": "PRD 骨架",
            "icon": "📋",
            "description": "输入需求描述，自动提取功能点和约束，生成结构化 PRD 文档",
            "inputLabel": "需求描述",
            "inputPlaceholder": "用自然语言描述你的产品需求...",
            "extraField": None,
            "nodes": [
                {"id": "extract_features", "label": "提取功能点"},
                {"id": "identify_constraints", "label": "识别约束条件"},
                {"id": "human_review", "label": "人工审核", "isHuman": True},
                {"id": "generate_prd", "label": "生成 PRD"},
            ],
            "resultKey": "prd",
        },
    },
]
