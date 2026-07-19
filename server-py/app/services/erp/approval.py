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
from datetime import datetime, timezone
from typing import Literal

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from pydantic import BaseModel, Field

from ..model import create_chat_model
from ...utils.llm_parse import parse_with_retry
from ...utils.logger import logger

model = create_chat_model(temperature=0.3)

# 审批角色定义
APPROVAL_ROLES = {
    "applicant": {
        "id": "applicant",
        "name": "申请人",
        "icon": "👤",
        "color": "#4f46e5",
        "desc": "提交申请，回答审批人的问题",
    },
    "manager": {
        "id": "manager",
        "name": "直属主管",
        "icon": "👔",
        "color": "#0891b2",
        "desc": "审核申请合理性，确认业务必要性",
    },
    "finance": {
        "id": "finance",
        "name": "财务专员",
        "icon": "💰",
        "color": "#059669",
        "desc": "审核费用合规性，确认金额和票据",
    },
    "hr": {"id": "hr", "name": "HR 专员", "icon": "📋", "color": "#d97706", "desc": "审核假期政策合规性，确认余额"},
    "director": {
        "id": "director",
        "name": "部门总监",
        "icon": "🏢",
        "color": "#dc2626",
        "desc": "大额报销或长期请假时的最终审批",
    },
}


def _get_role_system(role_id, form_data, form_type):
    """
    生成审批角色的系统提示词

    不同角色有不同的职责和检查要点
    """
    form_json = json.dumps(form_data, ensure_ascii=False, indent=2)
    applicant_name = form_data.get("applicantName", "小王")
    kind = "报销" if form_type == "expense" else "请假"

    systems = {
        "applicant": f"""你是{applicant_name}，正在提交{kind}申请。
申请内容：{form_json}
要求：简洁回答审批人的问题，提供必要的说明。语气自然，像真实对话。不超过60字。""",
        "manager": f"""你是直属主管，正在审核下属的{kind}申请。
申请内容：{form_json}
你的职责：
1. 判断这次{"报销是否有业务必要性" if form_type == "expense" else "请假是否影响团队工作"}
2. 金额或时间是否合理
3. 可以提问补充信息，然后给出批准/驳回/要求补充的意见
4. 语气严肃专业，像真实的主管。不超过80字。""",
        "finance": f"""你是财务专员，负责审核报销合规性。
申请内容：{form_json}
公司规定：
- 差旅：酒店每晚不超过800元，机票必须经济舱
- 餐饮：每次不超过500元
- 单笔超过3000元需附发票扫描件
你的职责：检查是否合规，发现问题要指出。不超过80字。""",
        "hr": f"""你是 HR 专员，负责审核请假合规性。
申请内容：{form_json}
假期规定：
- 年假：入职满1年后享有5天，每多1年增加1天，最多15天
- 事假：每年最多10天，超过3天影响年终绩效
- 病假：需提供医院证明
- 婚假：3天，需提供结婚证
你的职责：核实假期余额和规定。不超过80字。""",
        "director": f"""你是部门总监，只处理大额报销（>5000元）或长假（>5工作日）。
申请内容：{form_json}
你态度严格但公正，关注业务合理性和成本控制。
最终给出明确的批准或驳回，并说明理由。不超过100字。""",
    }
    return systems.get(role_id, systems["manager"])


def _plan_approval_flow(form_data, form_type):
    """
    规划审批流程

    根据表单类型和金额/天数决定审批节点：
    - 报销：manager → finance → director(>5000)
    - 请假：manager → hr → director(>5工作日)
    """
    flow = ["manager"]
    if form_type == "expense":
        flow.append("finance")
        amount = form_data.get("totalAmount", form_data.get("total_amount", 0))
        logger.info("erp: plan flow", {"formType": form_type, "amount": amount, "threshold": 5000})
        if amount > 5000:
            flow.append("director")
    else:
        flow.append("hr")
        workdays = form_data.get("workdays", 0)
        logger.info("erp: plan flow", {"formType": form_type, "workdays": workdays, "threshold": 5})
        if workdays > 5:
            flow.append("director")
    logger.info("erp: planned approvers", {"flow": flow})
    return flow


class ApprovalDecision(BaseModel):
    """审批 Agent 的结构化决定；未知或缺资料不能默认通过。"""

    action: Literal["approve", "reject", "needs_info"]
    comment: str = Field(min_length=1, max_length=500)


async def _request_decision(messages) -> ApprovalDecision:
    """要求模型返回受约束的决定，避免用关键词做 fail-open 判断。"""
    return await parse_with_retry(model, messages, ApprovalDecision)


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

    logger.info("erp: approver turn", {"roleId": role_id})

    decision_schema = (
        '只输出 JSON：{"action":"approve|reject|needs_info","comment":"意见或需要补充的问题"}。'
        "只有明确满足规则时才能 approve；资料不足用 needs_info；不符合规则用 reject。"
    )

    # 1. 审批人审核并返回结构化决定
    initial_decision = await _request_decision(
        [
            SystemMessage(system_prompt),
            HumanMessage(f"请审核这份申请。{decision_schema}"),
            *conversation_history,
        ]
    )
    initial_text = initial_decision.comment
    initial_type = "question" if initial_decision.action == "needs_info" else "decision"

    await emit_event(
        "message",
        {
            "from": role_id,
            "role": role,
            "content": initial_text,
            "type": initial_type,
            "action": initial_decision.action,
        },
    )
    conversation_history.append(AIMessage(f"[{role['name']}]：{initial_text}"))

    # 2. 资料不足时允许申请人补充一次，再要求明确决定
    if initial_decision.action == "needs_info" and role_id != "director":
        # 申请人回答
        applicant_system = _get_role_system("applicant", form_data, form_type)
        answer_response = await model.ainvoke(
            [
                SystemMessage(applicant_system),
                *conversation_history,
                HumanMessage(f"{role['name']}刚才提了问题，请以申请人身份回答"),
            ]
        )
        answer_text = answer_response.content

        await emit_event(
            "message",
            {
                "from": "applicant",
                "role": APPROVAL_ROLES["applicant"],
                "content": answer_text,
                "type": "answer",
            },
        )
        conversation_history.append(AIMessage(f"[申请人]：{answer_text}"))

        # 3. 审批人最终决定
        final_decision = await _request_decision(
            [
                SystemMessage(system_prompt),
                *conversation_history,
                HumanMessage(f"申请人已经补充信息，请给出最终决定。{decision_schema}"),
            ]
        )
        decision_text = final_decision.comment

        await emit_event(
            "message",
            {
                "from": role_id,
                "role": role,
                "content": decision_text,
                "type": "decision",
                "action": final_decision.action,
            },
        )
        conversation_history.append(AIMessage(f"[{role['name']}]：{decision_text}"))

        return {
            "action": final_decision.action,
            "approved": final_decision.action == "approve",
            "comment": decision_text,
        }

    return {
        "action": initial_decision.action,
        "approved": initial_decision.action == "approve",
        "comment": initial_text,
    }


async def run_approval_flow(form_data, form_type, emit_event, session_id):
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
    logger.info("erp: approval flow started", {"formType": form_type, "sessionId": session_id})

    # 1. 规划审批流
    approver_ids = _plan_approval_flow(form_data, form_type)
    approvers_data = [APPROVAL_ROLES[id] for id in approver_ids]

    await emit_event(
        "plan",
        {
            "approvers": approvers_data,
            "totalSteps": len(approver_ids),
        },
    )

    kind = "报销" if form_type == "expense" else "请假"
    conversation_history = [
        HumanMessage(f"申请人提交了{kind}申请：\n{json.dumps(form_data, ensure_ascii=False, indent=2)}"),
    ]

    all_approved = True
    final_status = "approved"
    final_comment = ""
    approver_results = []

    # 2. 依次执行每个审批人
    for role_id in approver_ids:
        role = APPROVAL_ROLES[role_id]
        await emit_event("approver_start", {"roleId": role_id, "role": role})

        result = await _run_approver_turn(role_id, form_data, form_type, conversation_history, emit_event)

        approver_results.append(
            {
                "roleId": role_id,
                "roleName": role["name"],
                "action": result["action"],
                "approved": result["approved"],
                "comment": result["comment"],
            }
        )

        await emit_event(
            "approver_done",
            {
                "roleId": role_id,
                "role": role,
                "action": result["action"],
                "approved": result["approved"],
                "comment": result["comment"],
            },
        )

        # 驳回或仍需补充资料都会终止预审，绝不默认通过
        if not result["approved"]:
            all_approved = False
            final_status = "rejected" if result["action"] == "reject" else "needs_info"
            action_label = "驳回" if final_status == "rejected" else "要求补充资料"
            final_comment = f"{role['name']}{action_label}：{result['comment']}"
            break

        final_comment = result["comment"]
        await asyncio.sleep(0.3)  # 间隔，避免过快

    # 3. 构建完整结果。这里只是 AI 预审模拟，不代表真实组织审批。
    completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    output = {
        "approved": all_approved,
        "status": final_status,
        "simulation": True,
        "comment": final_comment,
        "approvedBy": [r["roleName"] for r in approver_results if r["approved"]],
        "approverIds": approver_ids,
        "approvers": approvers_data,
        "approverResults": approver_results,
        "completedAt": completed_at.isoformat(),
        "sessionId": session_id,
    }

    await emit_event("final", output)
    logger.info("erp: approval flow done", {"formType": form_type, "approved": all_approved, "sessionId": session_id})
    return output
