"""
Multi-Agent 审批流模块

实现多人会签审批流程：
1. 规划审批流（根据表单类型和金额决定审批节点）
2. 每个审批节点由一个 Agent 角色执行
3. 支持追问（审批人提问 → 申请人回答 → 审批人决定）
4. 任一审批人驳回则流程终止
5. 审批记录持久化到 PostgreSQL
"""

import asyncio
import json
import uuid
from datetime import datetime

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from ..model import create_chat_model
from ...core.database import async_session_factory
from ...models.entities import ApprovalRecord
from ...utils.logger import logger

model = create_chat_model(temperature=0.3)

# 审批角色定义
APPROVAL_ROLES = {
    'applicant': {'id': 'applicant', 'name': '申请人', 'icon': '👤', 'color': '#4f46e5',
                  'desc': '提交申请，回答审批人的问题'},
    'manager': {'id': 'manager', 'name': '直属主管', 'icon': '👔', 'color': '#0891b2',
                'desc': '审核申请合理性，确认业务必要性'},
    'finance': {'id': 'finance', 'name': '财务专员', 'icon': '💰', 'color': '#059669',
                'desc': '审核费用合规性，确认金额和票据'},
    'hr': {'id': 'hr', 'name': 'HR 专员', 'icon': '📋', 'color': '#d97706',
           'desc': '审核假期政策合规性，确认余额'},
    'director': {'id': 'director', 'name': '部门总监', 'icon': '🏢', 'color': '#dc2626',
                 'desc': '大额报销或长期请假时的最终审批'},
}


def _get_role_system(role_id, form_data, form_type):
    """
    生成审批角色的系统提示词

    不同角色有不同的职责和检查要点
    """
    form_json = json.dumps(form_data, ensure_ascii=False, indent=2)
    applicant_name = form_data.get('applicantName', '小王')
    kind = '报销' if form_type == 'expense' else '请假'

    systems = {
        'applicant': f"""你是{applicant_name}，正在提交{kind}申请。
申请内容：{form_json}
要求：简洁回答审批人的问题，提供必要的说明。语气自然，像真实对话。不超过60字。""",

        'manager': f"""你是直属主管，正在审核下属的{kind}申请。
申请内容：{form_json}
你的职责：
1. 判断这次{'报销是否有业务必要性' if form_type == 'expense' else '请假是否影响团队工作'}
2. 金额或时间是否合理
3. 可以提问补充信息，然后给出批准/驳回/要求补充的意见
4. 语气严肃专业，像真实的主管。不超过80字。""",

        'finance': f"""你是财务专员，负责审核报销合规性。
申请内容：{form_json}
公司规定：
- 差旅：酒店每晚不超过800元，机票必须经济舱
- 餐饮：每次不超过500元
- 单笔超过3000元需附发票扫描件
你的职责：检查是否合规，发现问题要指出。不超过80字。""",

        'hr': f"""你是 HR 专员，负责审核请假合规性。
申请内容：{form_json}
假期规定：
- 年假：入职满1年后享有5天，每多1年增加1天，最多15天
- 事假：每年最多10天，超过3天影响年终绩效
- 病假：需提供医院证明
- 婚假：3天，需提供结婚证
你的职责：核实假期余额和规定。不超过80字。""",

        'director': f"""你是部门总监，只处理大额报销（>5000元）或长假（>5工作日）。
申请内容：{form_json}
你态度严格但公正，关注业务合理性和成本控制。
最终给出明确的批准或驳回，并说明理由。不超过100字。""",
    }
    return systems.get(role_id, systems['manager'])


def _plan_approval_flow(form_data, form_type):
    """
    规划审批流程

    根据表单类型和金额/天数决定审批节点：
    - 报销：manager → finance → director(>5000)
    - 请假：manager → hr → director(>5工作日)
    """
    flow = ['manager']
    if form_type == 'expense':
        flow.append('finance')
        amount = form_data.get('totalAmount', form_data.get('total_amount', 0))
        logger.info('erp: plan flow', {'formType': form_type, 'amount': amount, 'threshold': 5000})
        if amount > 5000:
            flow.append('director')
    else:
        flow.append('hr')
        workdays = form_data.get('workdays', 0)
        logger.info('erp: plan flow', {'formType': form_type, 'workdays': workdays, 'threshold': 5})
        if workdays > 5:
            flow.append('director')
    logger.info('erp: planned approvers', {'flow': flow})
    return flow


def _is_approved(text):
    """判断是否为批准"""
    reject_keywords = ['驳回', '不批', '拒绝', '不同意', '不予批准', '无法批准']
    return not any(kw in text for kw in reject_keywords)


async def _run_approver_turn(role_id, form_data, form_type, conversation_history, emit_event):
    """
    执行单个审批人的审核

    流程：
    1. 审批人查看申请，给出意见
    2. 如有问题，追问申请人
    3. 申请人回答
    4. 审批人给出最终决定
    """
    role = APPROVAL_ROLES[role_id]
    system_prompt = _get_role_system(role_id, form_data, form_type)

    logger.info('erp: approver turn', {'roleId': role_id})

    # 1. 审批人审核
    question_response = await model.ainvoke([
        SystemMessage(system_prompt),
        HumanMessage('请审核这份申请。如果有疑问，可以提问；如果信息充分，直接给出审批意见（批准/驳回）。'),
        *conversation_history,
    ])
    question_text = question_response.content

    await emit_event('message', {
        'from': role_id,
        'role': role,
        'content': question_text,
        'type': 'question',
    })
    conversation_history.append(AIMessage(f'[{role["name"]}]：{question_text}'))

    # 2. 检查是否有追问（问号）
    has_question = any(kw in question_text for kw in ['？', '?', '请问', '能否'])

    if has_question and role_id != 'director':
        # 申请人回答
        applicant_system = _get_role_system('applicant', form_data, form_type)
        answer_response = await model.ainvoke([
            SystemMessage(applicant_system),
            *conversation_history,
            HumanMessage(f'{role["name"]}刚才提了问题，请以申请人身份回答'),
        ])
        answer_text = answer_response.content

        await emit_event('message', {
            'from': 'applicant',
            'role': APPROVAL_ROLES['applicant'],
            'content': answer_text,
            'type': 'answer',
        })
        conversation_history.append(AIMessage(f'[申请人]：{answer_text}'))

        # 3. 审批人最终决定
        decision_response = await model.ainvoke([
            SystemMessage(system_prompt),
            *conversation_history,
            HumanMessage('申请人已经回答了你的问题，现在请给出最终的审批意见：批准或驳回，并说明理由。'),
        ])
        decision_text = decision_response.content

        await emit_event('message', {
            'from': role_id,
            'role': role,
            'content': decision_text,
            'type': 'decision',
        })
        conversation_history.append(AIMessage(f'[{role["name"]}]：{decision_text}'))

        return {'approved': _is_approved(decision_text), 'comment': decision_text}

    return {'approved': _is_approved(question_text), 'comment': question_text}


async def _save_approval_record(
    session_id: str,
    form_type: str,
    form_data: dict,
    flow_json: dict,
    approvers: list,
    status: str,
    final_comment: str,
    result_json: dict,
    completed_at: datetime = None,
):
    """保存审批记录到 PostgreSQL"""
    async with async_session_factory() as session:
        record = ApprovalRecord(
            id=uuid.uuid4(),
            session_id=session_id,
            form_type=form_type,
            form_data=form_data,
            flow_json=flow_json,
            approvers=approvers,
            status=status,
            final_comment=final_comment,
            result_json=result_json,
            completed_at=completed_at,
        )
        session.add(record)
        await session.commit()
        logger.info('erp: record saved', {'id': str(record.id)})
        return str(record.id)


async def run_approval_flow(form_data, form_type, emit_event, session_id=None):
    """
    执行完整的审批流程

    参数：
    - form_data: 表单数据
    - form_type: 表单类型（expense/leave）
    - emit_event: 事件回调，用于 SSE 推送
    - session_id: 会话ID（用于关联记录）

    SSE 事件：
    - plan: 审批流程规划
    - approver_start: 审批人开始
    - message: 审批消息
    - approver_done: 审批人完成
    - final: 最终结果
    """
    if session_id is None:
        session_id = str(uuid.uuid4())

    logger.info('erp: approval flow started', {'formType': form_type, 'sessionId': session_id})

    # 1. 规划审批流
    approver_ids = _plan_approval_flow(form_data, form_type)
    approvers_data = [APPROVAL_ROLES[id] for id in approver_ids]

    await emit_event('plan', {
        'approvers': approvers_data,
        'totalSteps': len(approver_ids),
    })

    kind = '报销' if form_type == 'expense' else '请假'
    conversation_history = [
        HumanMessage(f'申请人提交了{kind}申请：\n{json.dumps(form_data, ensure_ascii=False, indent=2)}'),
    ]

    all_approved = True
    final_comment = ''
    approver_results = []

    # 2. 依次执行每个审批人
    for role_id in approver_ids:
        role = APPROVAL_ROLES[role_id]
        await emit_event('approver_start', {'roleId': role_id, 'role': role})

        result = await _run_approver_turn(
            role_id, form_data, form_type, conversation_history, emit_event
        )

        approver_results.append({
            'roleId': role_id,
            'roleName': role['name'],
            'approved': result['approved'],
            'comment': result['comment'],
        })

        await emit_event('approver_done', {
            'roleId': role_id, 'role': role,
            'approved': result['approved'], 'comment': result['comment'],
        })

        # 驳回则终止流程
        if not result['approved']:
            all_approved = False
            final_comment = f'被{role["name"]}驳回：{result["comment"]}'
            break

        final_comment = result['comment']
        await asyncio.sleep(0.3)  # 间隔，避免过快

    # 3. 构建流程定义
    flow_json = {
        'approverIds': approver_ids,
        'flow': approver_ids,
    }

    # 4. 构建完整结果
    completed_at = datetime.utcnow()
    output = {
        'approved': all_approved,
        'status': 'approved' if all_approved else 'rejected',
        'comment': final_comment,
        'approvedBy': [APPROVAL_ROLES[id]['name'] for id in approver_ids] if all_approved else [],
        'completedAt': completed_at.isoformat(),
        'sessionId': session_id,
    }

    # 5. 持久化到 PostgreSQL
    record_id = await _save_approval_record(
        session_id=session_id,
        form_type=form_type,
        form_data=form_data,
        flow_json=flow_json,
        approvers=approvers_data,
        status=output['status'],
        final_comment=final_comment,
        result_json={
            'allApproved': all_approved,
            'approverResults': approver_results,
            'finalComment': final_comment,
        },
        completed_at=completed_at,
    )
    output['recordId'] = record_id

    await emit_event('final', output)
    logger.info('erp: approval flow done', {'formType': form_type, 'approved': all_approved, 'recordId': record_id})
    return output


async def get_approval_records(session_id: str = None, status: str = None, limit: int = 20) -> list:
    """
    查询审批记录

    参数：
    - session_id: 可选，限定会话ID
    - status: 可选，限定状态（pending/approved/rejected）
    - limit: 返回数量限制
    """
    from sqlalchemy import select, desc

    async with async_session_factory() as session:
        query = select(ApprovalRecord).order_by(desc(ApprovalRecord.created_at))

        if session_id:
            query = query.where(ApprovalRecord.session_id == session_id)
        if status:
            query = query.where(ApprovalRecord.status == status)

        result = await session.execute(query.limit(limit))
        records = result.scalars().all()

    return [
        {
            'id': str(r.id),
            'sessionId': r.session_id,
            'formType': r.form_type,
            'formData': r.form_data,
            'status': r.status,
            'finalComment': r.final_comment,
            'approvedBy': [a['name'] for a in (r.approvers or [])],
            'createdAt': r.created_at.isoformat() if r.created_at else None,
            'completedAt': r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in records
    ]