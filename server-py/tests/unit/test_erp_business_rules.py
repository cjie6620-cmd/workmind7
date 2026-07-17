"""ERP 预审的业务边界与 fail-closed 回归测试。"""

from datetime import date
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.routes.erp import _validated_form
from app.services.erp import approval
from app.services.erp import parser as erp_parser
from app.services.erp.parser import ExpenseForm, LeaveForm


def test_expense_total_is_recomputed_from_positive_items():
    form = ExpenseForm.model_validate(
        {
            "type": "meal",
            "items": [
                {"name": "午餐", "amount": 38.6},
                {"name": "晚餐", "amount": 41.4},
            ],
            "totalAmount": 9999,
            "reason": "客户现场支持",
        }
    )

    assert form.total_amount == 80


def test_expense_rejects_negative_item_amount():
    with pytest.raises(ValidationError):
        ExpenseForm.model_validate(
            {
                "type": "meal",
                "items": [{"name": "冲销", "amount": -10}],
                "totalAmount": -10,
                "reason": "非法金额",
            }
        )


def test_leave_dates_are_ordered_and_duration_is_server_computed():
    form = LeaveForm.model_validate(
        {
            "type": "annual",
            "startDate": "2026-07-13",
            "endDate": "2026-07-15",
            "days": 99,
            "workdays": 99,
            "reason": "休假",
        }
    )
    assert form.days == 3
    assert form.workdays == 3

    with pytest.raises(ValidationError):
        LeaveForm.model_validate(
            {
                "type": "annual",
                "startDate": "2026-07-15",
                "endDate": "2026-07-13",
                "days": 1,
                "workdays": 1,
                "reason": "逆序日期",
            }
        )


def test_submission_is_normalized_to_json_safe_camel_case():
    result = _validated_form(
        "leave",
        {
            "type": "personal",
            "startDate": "2026-07-18",
            "endDate": "2026-07-19",
            "days": 20,
            "workdays": 20,
            "reason": "家庭事务",
        },
    )

    assert result["startDate"] == "2026-07-18"
    assert result["days"] == 2
    assert result["workdays"] == 0


@pytest.mark.asyncio
async def test_relative_date_prompt_uses_configured_business_day(monkeypatch):
    parse_result = AsyncMock(return_value=object())
    monkeypatch.setattr(erp_parser, "business_date", lambda: date(2026, 7, 16))
    monkeypatch.setattr(erp_parser, "parse_with_retry", parse_result)

    await erp_parser.parse_expense_form("上周出差")
    await erp_parser.parse_leave_form("明天请假")

    prompts = [call.args[1][0]["content"] for call in parse_result.await_args_list]
    assert all("今天是 2026-07-16" in prompt for prompt in prompts)


@pytest.mark.asyncio
async def test_approval_needs_info_never_defaults_to_approved(monkeypatch):
    monkeypatch.setattr(
        approval,
        "_run_approver_turn",
        AsyncMock(
            return_value={
                "action": "needs_info",
                "approved": False,
                "comment": "请补充发票",
            }
        ),
    )
    emit = AsyncMock()

    result = await approval.run_approval_flow(
        {"totalAmount": 100, "applicantName": "alice"},
        "expense",
        emit,
        "APP_test",
    )

    assert result["approved"] is False
    assert result["status"] == "needs_info"
    assert result["simulation"] is True
    assert any(call.args[0] == "final" for call in emit.await_args_list)


@pytest.mark.asyncio
async def test_approval_all_explicit_approvals_complete(monkeypatch):
    monkeypatch.setattr(
        approval,
        "_run_approver_turn",
        AsyncMock(
            return_value={
                "action": "approve",
                "approved": True,
                "comment": "符合预审规则",
            }
        ),
    )
    monkeypatch.setattr(approval.asyncio, "sleep", AsyncMock())

    result = await approval.run_approval_flow(
        {"totalAmount": 100, "applicantName": "alice"},
        "expense",
        AsyncMock(),
        "APP_test",
    )

    assert result["approved"] is True
    assert result["status"] == "approved"
    assert [item["action"] for item in result["approverResults"]] == ["approve", "approve"]
