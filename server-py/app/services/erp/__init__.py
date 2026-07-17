"""
ERP 服务模块

提供智能填单和审批流功能：
- parser: 自然语言表单解析
- approval: Multi-Agent 审批流程
"""

from .parser import parse_expense_form, parse_leave_form
from .approval import run_approval_flow, APPROVAL_ROLES

__all__ = [
    "parse_expense_form",
    "parse_leave_form",
    "run_approval_flow",
    "APPROVAL_ROLES",
]
