# 四个内置工作流模板
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from ..model import create_chat_model
from ...utils.logger import logger

model = create_chat_model(temperature=0.7)
model0 = create_chat_model(temperature=0)
parser = StrOutputParser()
checkpointer = MemorySaver()


# ══════════════════════════════════════════════════════════════
# 工作流一：周报生成
# ══════════════════════════════════════════════════════════════

class WeeklyReportState(TypedDict):
    points: str
    dept: str
    highlights: str
    risks: str
    next_plan: str
    report: str
    human_feedback: str


def build_weekly_report():
    def extract_highlights(state: WeeklyReportState):
        logger.info('workflow:weekly → extractHighlights')
        chain = ChatPromptTemplate.from_messages([
            ('system', '你是写作助手，从工作要点中提炼亮点。输出3-5条，每条一行，用"• "开头，不超过30字。'),
            ('human', '工作要点：\n{points}'),
        ]) | model | parser
        return {'highlights': chain.invoke({'points': state['points']})}

    def identify_risks(state: WeeklyReportState):
        logger.info('workflow:weekly → identifyRisks')
        chain = ChatPromptTemplate.from_messages([
            ('system', '从工作内容中识别风险和阻塞项。如果没有明显风险，输出"本周无明显风险项"。输出2-3条，每条一行。'),
            ('human', '工作要点：\n{points}'),
        ]) | model0 | parser
        return {'risks': chain.invoke({'points': state['points']})}

    def human_review(state: WeeklyReportState):
        logger.info('workflow:weekly → humanReview (waiting)')
        return {}

    def generate_report(state: WeeklyReportState):
        logger.info('workflow:weekly → generateReport')
        feedback = f'\n\n注意事项：{state["human_feedback"]}' if state.get("human_feedback") else ''
        chain = ChatPromptTemplate.from_messages([
            ('system', f'你是专业的报告撰写助手，生成结构清晰的周报。{feedback}'),
            ('human', """部门：{dept}
本周工作亮点：
{highlights}

风险与阻塞：
{risks}

请生成一份完整的周工作报告，格式：
## 本周工作总结
（整合亮点，用叙述方式）

## 主要成果
（具体成果，带数据更好）

## 风险与阻塞
（风险项及应对措施）

## 下周计划
（3-5条，具体可执行）"""),
        ]) | model | parser
        return {'report': chain.invoke({
            'dept': state.get('dept', '研发部'),
            'highlights': state['highlights'],
            'risks': state['risks'],
        })}

    g = StateGraph(WeeklyReportState)
    g.add_node('extract_highlights', extract_highlights)
    g.add_node('identify_risks', identify_risks)
    g.add_node('human_review', human_review)
    g.add_node('generate_report', generate_report)
    g.add_edge(START, 'extract_highlights')
    g.add_edge('extract_highlights', 'identify_risks')
    g.add_edge('identify_risks', 'human_review')
    g.add_edge('human_review', 'generate_report')
    g.add_edge('generate_report', END)
    return g.compile(checkpointer=checkpointer, interrupt_before=['human_review'])


# ══════════════════════════════════════════════════════════════
# 工作流二：会议纪要
# ══════════════════════════════════════════════════════════════

class MeetingMinutesState(TypedDict):
    raw_notes: str
    meeting_title: str
    attendees: str
    conclusions: str
    action_items: str
    minutes: str
    human_feedback: str


def build_meeting_minutes():
    def extract_attendees(state: MeetingMinutesState):
        logger.info('workflow:meeting → extractAttendees')
        chain = ChatPromptTemplate.from_messages([
            ('system', '从会议记录中提取参会人员和主要议题。格式：参会人：xxx、xxx\n主要议题：xxx'),
            ('human', '会议记录：\n{raw_notes}'),
        ]) | model0 | parser
        return {'attendees': chain.invoke({'raw_notes': state['raw_notes']})}

    def extract_conclusions(state: MeetingMinutesState):
        logger.info('workflow:meeting → extractConclusions')
        chain = ChatPromptTemplate.from_messages([
            ('system', '从会议记录中提取达成的结论和决策，每条以"✓"开头，不超过25字。如无明确结论，写"待下次会议确认"。'),
            ('human', '会议记录：\n{raw_notes}'),
        ]) | model0 | parser
        return {'conclusions': chain.invoke({'raw_notes': state['raw_notes']})}

    def extract_actions(state: MeetingMinutesState):
        logger.info('workflow:meeting → extractActions')
        chain = ChatPromptTemplate.from_messages([
            ('system', """从会议记录中提取 Action Items（后续行动项）。
每条格式：【负责人】事项内容（截止时间）
如果没有明确负责人，写"待定"。如果没有截止时间，写"尽快"。"""),
            ('human', '会议记录：\n{raw_notes}'),
        ]) | model0 | parser
        return {'action_items': chain.invoke({'raw_notes': state['raw_notes']})}

    def human_review(state: MeetingMinutesState):
        return {}

    def generate_minutes(state: MeetingMinutesState):
        logger.info('workflow:meeting → generateMinutes')
        from datetime import datetime
        today = datetime.now().strftime('%Y/%m/%d')
        feedback = f'\n修改意见：{state["human_feedback"]}' if state.get("human_feedback") else ''
        chain = ChatPromptTemplate.from_messages([
            ('system', f'你是会议纪要撰写助手，生成正式会议纪要。{feedback}'),
            ('human', """会议名称：{title}
日期：{today}
{attendees}

请生成正式会议纪要，包含：
## 会议基本信息
## 会议议题与讨论
## 会议结论
{conclusions}
## Action Items
{action_items}
## 备注"""),
        ]) | model | parser
        return {'minutes': chain.invoke({
            'title': state.get('meeting_title', '工作例会'),
            'today': today,
            'attendees': state['attendees'],
            'conclusions': state['conclusions'],
            'action_items': state['action_items'],
        })}

    g = StateGraph(MeetingMinutesState)
    g.add_node('extract_attendees', extract_attendees)
    g.add_node('extract_conclusions', extract_conclusions)
    g.add_node('extract_actions', extract_actions)
    g.add_node('human_review', human_review)
    g.add_node('generate_minutes', generate_minutes)
    g.add_edge(START, 'extract_attendees')
    g.add_edge('extract_attendees', 'extract_conclusions')
    g.add_edge('extract_conclusions', 'extract_actions')
    g.add_edge('extract_actions', 'human_review')
    g.add_edge('human_review', 'generate_minutes')
    g.add_edge('generate_minutes', END)
    return g.compile(checkpointer=checkpointer, interrupt_before=['human_review'])


# ══════════════════════════════════════════════════════════════
# 工作流三：邮件润色
# ══════════════════════════════════════════════════════════════

class EmailPolishState(TypedDict):
    draft: str
    recipient: str
    purpose: str
    issues: str
    polished: str
    human_feedback: str


def build_email_polish():
    def analyze_intent(state: EmailPolishState):
        logger.info('workflow:email → analyzeIntent')
        chain = ChatPromptTemplate.from_messages([
            ('system', '分析邮件的写作目的、语气和受众，输出2-3句话的简短分析。'),
            ('human', '收件人：{recipient}\n邮件草稿：\n{draft}'),
        ]) | model0 | parser
        return {'purpose': chain.invoke({'draft': state['draft'], 'recipient': state.get('recipient', '对方')})}

    def check_issues(state: EmailPolishState):
        logger.info('workflow:email → checkIssues')
        chain = ChatPromptTemplate.from_messages([
            ('system', """检查邮件草稿的问题，按优先级列出，每条不超过20字。
检查维度：语气是否合适、逻辑是否清晰、用词是否专业、有无歧义、结尾是否得体。
如果没有明显问题，输出"整体质量良好，建议微调措辞使其更专业"。"""),
            ('human', '邮件草稿：\n{draft}'),
        ]) | model0 | parser
        return {'issues': chain.invoke({'draft': state['draft']})}

    def human_review(state: EmailPolishState):
        return {}

    def polish_email(state: EmailPolishState):
        logger.info('workflow:email → polishEmail')
        feedback = f'\n用户要求：{state["human_feedback"]}' if state.get("human_feedback") else ''
        chain = ChatPromptTemplate.from_messages([
            ('system', f'你是专业邮件润色助手，根据分析结果优化邮件。{feedback}\n保持原意，不改变核心内容，只优化表达。输出完整的润色后邮件，包括称呼、正文、结尾。'),
            ('human', """原始草稿：
{draft}

写作目的分析：{purpose}

发现的问题：{issues}

请输出润色后的完整邮件："""),
        ]) | model | parser
        return {'polished': chain.invoke({
            'draft': state['draft'],
            'purpose': state['purpose'],
            'issues': state['issues'],
        })}

    g = StateGraph(EmailPolishState)
    g.add_node('analyze_intent', analyze_intent)
    g.add_node('check_issues', check_issues)
    g.add_node('human_review', human_review)
    g.add_node('polish_email', polish_email)
    g.add_edge(START, 'analyze_intent')
    g.add_edge('analyze_intent', 'check_issues')
    g.add_edge('check_issues', 'human_review')
    g.add_edge('human_review', 'polish_email')
    g.add_edge('polish_email', END)
    return g.compile(checkpointer=checkpointer, interrupt_before=['human_review'])


# ══════════════════════════════════════════════════════════════
# 工作流四：PRD 骨架
# ══════════════════════════════════════════════════════════════

class PrdSkeletonState(TypedDict):
    description: str
    features: str
    constraints: str
    prd: str
    human_feedback: str


def build_prd_skeleton():
    def extract_features(state: PrdSkeletonState):
        logger.info('workflow:prd → extractFeatures')
        chain = ChatPromptTemplate.from_messages([
            ('system', '从需求描述中提取核心功能点。按优先级排序，格式：P0/P1/P2 + 功能描述，每条一行。'),
            ('human', '需求描述：\n{description}'),
        ]) | model0 | parser
        return {'features': chain.invoke({'description': state['description']})}

    def identify_constraints(state: PrdSkeletonState):
        logger.info('workflow:prd → identifyConstraints')
        chain = ChatPromptTemplate.from_messages([
            ('system', """从需求中识别技术约束和业务约束。
技术约束：性能要求、兼容性、安全性等。
业务约束：时间限制、预算、合规要求等。
如果描述中没有提及，写"待确认"。"""),
            ('human', '需求描述：\n{description}'),
        ]) | model0 | parser
        return {'constraints': chain.invoke({'description': state['description']})}

    def human_review(state: PrdSkeletonState):
        return {}

    def generate_prd(state: PrdSkeletonState):
        logger.info('workflow:prd → generatePrd')
        feedback = f'\n补充说明：{state["human_feedback"]}' if state.get("human_feedback") else ''
        chain = ChatPromptTemplate.from_messages([
            ('system', f'你是产品经理助手，生成结构化 PRD 文档骨架。{feedback}\n输出完整的 Markdown 格式 PRD，各章节有具体内容，不要只写标题。'),
            ('human', """需求描述：{description}

功能点：
{features}

约束条件：
{constraints}

生成 PRD 文档，包含以下章节：
## 一、背景与目标
## 二、核心功能
## 三、详细需求
## 四、非功能需求
## 五、验收标准
## 六、里程碑计划"""),
        ]) | model | parser
        return {'prd': chain.invoke({
            'description': state['description'],
            'features': state['features'],
            'constraints': state['constraints'],
        })}

    g = StateGraph(PrdSkeletonState)
    g.add_node('extract_features', extract_features)
    g.add_node('identify_constraints', identify_constraints)
    g.add_node('human_review', human_review)
    g.add_node('generate_prd', generate_prd)
    g.add_edge(START, 'extract_features')
    g.add_edge('extract_features', 'identify_constraints')
    g.add_edge('identify_constraints', 'human_review')
    g.add_edge('human_review', 'generate_prd')
    g.add_edge('generate_prd', END)
    return g.compile(checkpointer=checkpointer, interrupt_before=['human_review'])


# ── 注册表 ──────────────────────────────────────────────────

WORKFLOW_BUILDERS = {
    'weekly_report': build_weekly_report,
    'meeting_minutes': build_meeting_minutes,
    'email_polish': build_email_polish,
    'prd_skeleton': build_prd_skeleton,
}

WORKFLOW_META = {
    'weekly_report': {
        'id': 'weekly_report', 'title': '周报生成', 'icon': '📊',
        'desc': '输入本周工作要点，自动提炼亮点、识别风险，生成规范周报',
        'inputLabel': '本周工作要点',
        'inputPlaceholder': '请简单描述本周完成的主要工作，一条一行...',
        'extraField': {'key': 'dept', 'label': '部门名称', 'placeholder': '如：前端研发组'},
        'nodes': [
            {'id': 'extract_highlights', 'label': '提炼工作亮点'},
            {'id': 'identify_risks', 'label': '识别风险阻塞'},
            {'id': 'human_review', 'label': '人工审核', 'isHuman': True},
            {'id': 'generate_report', 'label': '生成周报'},
        ],
        'resultKey': 'report',
    },
    'meeting_minutes': {
        'id': 'meeting_minutes', 'title': '会议纪要', 'icon': '📝',
        'desc': '粘贴会议原始记录，自动提取结论和 Action Items，生成正式纪要',
        'inputLabel': '会议原始记录',
        'inputPlaceholder': '粘贴会议记录，包括讨论内容、发言摘要等...',
        'extraField': {'key': 'meetingTitle', 'label': '会议名称', 'placeholder': '如：产品周会 2024-03'},
        'nodes': [
            {'id': 'extract_attendees', 'label': '提取参会人与议题'},
            {'id': 'extract_conclusions', 'label': '提取会议结论'},
            {'id': 'extract_actions', 'label': '整理 Action Items'},
            {'id': 'human_review', 'label': '人工审核', 'isHuman': True},
            {'id': 'generate_minutes', 'label': '生成纪要'},
        ],
        'resultKey': 'minutes',
    },
    'email_polish': {
        'id': 'email_polish', 'title': '邮件润色', 'icon': '✉️',
        'desc': '输入邮件草稿，AI 分析语气和问题，润色成正式邮件',
        'inputLabel': '邮件草稿',
        'inputPlaceholder': '粘贴你的邮件草稿...',
        'extraField': {'key': 'recipient', 'label': '收件人/场景', 'placeholder': '如：客户、上级、合作方'},
        'nodes': [
            {'id': 'analyze_intent', 'label': '分析写作意图'},
            {'id': 'check_issues', 'label': '检查问题'},
            {'id': 'human_review', 'label': '人工审核', 'isHuman': True},
            {'id': 'polish_email', 'label': '生成润色版本'},
        ],
        'resultKey': 'polished',
    },
    'prd_skeleton': {
        'id': 'prd_skeleton', 'title': 'PRD 骨架', 'icon': '📋',
        'desc': '输入需求描述，自动提取功能点和约束，生成结构化 PRD 文档',
        'inputLabel': '需求描述',
        'inputPlaceholder': '用自然语言描述你的产品需求...',
        'nodes': [
            {'id': 'extract_features', 'label': '提取功能点'},
            {'id': 'identify_constraints', 'label': '识别约束条件'},
            {'id': 'human_review', 'label': '人工审核', 'isHuman': True},
            {'id': 'generate_prd', 'label': '生成 PRD'},
        ],
        'resultKey': 'prd',
    },
}
