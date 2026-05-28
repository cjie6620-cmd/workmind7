"""
表单解析模块

将自然语言描述转换为结构化表单：
1. 报销单解析（expense）
2. 请假单解析（leave）
3. 合规检查（报销限额）
"""

from datetime import datetime
from typing import List, Optional, Literal

from pydantic import BaseModel, Field

from ..model import create_chat_model
from ...utils.llm_parse import parse_with_retry

model = create_chat_model(temperature=0)


# ── 报销申请 ────────────────────────────────────────────────

class ExpenseItem(BaseModel):
    """报销明细项"""
    name: str = Field(description='费用项目名称，如"高铁票""住宿费"')
    amount: float = Field(description='金额，单位：元')
    date: Optional[str] = Field(default=None, description='发生日期 YYYY-MM-DD')
    note: Optional[str] = Field(default=None, description='备注')


class ExpenseForm(BaseModel):
    """报销单表单"""
    type: Literal['travel', 'meal', 'office', 'training', 'other'] = Field(
        description='费用类型：travel=差旅, meal=餐饮, office=办公用品, training=培训, other=其他'
    )
    items: List[ExpenseItem] = Field(description='费用明细列表')
    total_amount: float = Field(description='总金额，单位：元')
    reason: str = Field(description='报销事由，20字以内')
    dept: Optional[str] = Field(default=None, description='报销部门')
    warnings: List[str] = Field(default_factory=list, description='异常或需要注意的地方')


# 报销解析的输出格式说明
_EXPENSE_SCHEMA = """返回纯 JSON，格式：
{"type": "travel"|"meal"|"office"|"training"|"other", "items": [{"name": str, "amount": float, "date": str|null, "note": str|null}], "total_amount": float, "reason": str, "dept": str|null, "warnings": [str]}"""



async def parse_expense_form(text):
    """
    解析报销申请

    从自然语言描述中提取：
    - 费用类型
    - 费用明细（名称、金额、日期）
    - 总金额
    - 报销事由
    """
    today = datetime.now().strftime('%Y-%m-%d')
    messages = [
        {'role': 'system', 'content': f"""你是报销单填写助手。从用户的自然语言描述中提取报销信息，生成结构化表单。
今天是 {today}。
规则：
1. 如果用户说"上周"，根据今天日期推算具体日期
2. 金额务必精确，提到"约""大概"时保留原数字
3. 如果描述中有金额超过单笔3000元的项目，在 warnings 里提示
4. 如果报销事由不明确，在 warnings 里提示需要补充
5. total_amount 等于所有 items 的 amount 之和

{_EXPENSE_SCHEMA}"""},
        {'role': 'user', 'content': text},
    ]
    return await parse_with_retry(model, messages, ExpenseForm)


# ── 请假申请 ────────────────────────────────────────────────

class LeaveForm(BaseModel):
    """请假单表单"""
    type: Literal['annual', 'personal', 'sick', 'compensatory', 'marriage', 'maternity'] = Field(
        description='假期类型：annual=年假, personal=事假, sick=病假, compensatory=调休, marriage=婚假, maternity=产假'
    )
    start_date: str = Field(description='开始日期 YYYY-MM-DD')
    end_date: str = Field(description='结束日期 YYYY-MM-DD')
    days: float = Field(description='请假天数（自然日）')
    workdays: float = Field(description='工作日天数（排除周末）')
    reason: str = Field(description='请假原因，30字以内')
    emergency_contact: Optional[str] = Field(default=None, description='紧急联系人')
    warnings: List[str] = Field(default_factory=list)


_LEAVE_SCHEMA = """返回纯 JSON，格式：
{"type": "annual"|"personal"|"sick"|"compensatory"|"marriage"|"maternity", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "days": float, "workdays": float, "reason": str, "emergency_contact": str|null, "warnings": [str]}"""


def _count_workdays(start_str, end_str):
    """
    计算两个日期之间的工作日数（排除周六周日）

    用于请假单的 workdays 字段
    """
    from datetime import timedelta
    start = datetime.strptime(start_str, '%Y-%m-%d')
    end = datetime.strptime(end_str, '%Y-%m-%d')
    count = 0
    d = start
    while d <= end:
        if d.weekday() < 5:  # 周一到周五
            count += 1
        d += timedelta(days=1)
    return count


async def parse_leave_form(text):
    """
    解析请假申请

    从自然语言描述中提取：
    - 假期类型
    - 开始/结束日期
    - 请假天数（自然日 + 工作日）
    - 请假原因
    """
    today = datetime.now().strftime('%Y-%m-%d')
    messages = [
        {'role': 'system', 'content': f"""你是请假申请助手。从用户的自然语言描述中提取请假信息。
今天是 {today}。
规则：
1. "下周一到周三"等相对日期要换算成具体日期
2. days 是自然日（含周末），workdays 是工作日（不含周末）
3. 请假超过3个工作日时，在 warnings 里提示需要主管和 HR 双重审批
4. 病假要在 warnings 里提示需要提供医院证明
5. 产假/婚假要在 warnings 里提示需要提供相关证明材料

{_LEAVE_SCHEMA}"""},
        {'role': 'user', 'content': text},
    ]
    result = await parse_with_retry(model, messages, LeaveForm)

    # 重新计算工作日数（更精确）
    if result.start_date and result.end_date:
        result.workdays = _count_workdays(result.start_date, result.end_date)

    return result