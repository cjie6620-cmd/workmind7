"""
表单解析模块

将自然语言描述转换为结构化表单：
1. 报销单解析（expense）
2. 请假单解析（leave）
3. 合规检查（报销限额）
"""

from datetime import date as DateType, datetime, timedelta
from typing import List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from ..model import create_chat_model
from ...utils.business_time import business_date
from ...utils.llm_parse import parse_with_retry

model = create_chat_model(temperature=0)


class CamelModel(BaseModel):
    """统一 camelCase 输出的基类，前后端字段名一致"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ── 报销申请 ────────────────────────────────────────────────


class ExpenseItem(CamelModel):
    """报销明细项"""

    name: str = Field(min_length=1, max_length=100, description='费用项目名称，如"高铁票""住宿费"')
    amount: float = Field(gt=0, le=100_000_000, description="金额，单位：元，必须大于 0")
    date: Optional[DateType] = Field(default=None, description="发生日期 YYYY-MM-DD")
    note: Optional[str] = Field(default=None, max_length=500, description="备注")


class ExpenseForm(CamelModel):
    """报销单表单"""

    type: Literal["travel", "meal", "office", "training", "other"] = Field(
        description="费用类型：travel=差旅, meal=餐饮, office=办公用品, training=培训, other=其他"
    )
    items: List[ExpenseItem] = Field(min_length=1, max_length=100, description="费用明细列表")
    total_amount: float = Field(gt=0, le=100_000_000, description="总金额，单位：元")
    reason: str = Field(min_length=1, max_length=200, description="报销事由")
    dept: Optional[str] = Field(default=None, max_length=64, description="报销部门")
    warnings: List[str] = Field(default_factory=list, description="异常或需要注意的地方")

    @model_validator(mode="after")
    def recompute_total(self):
        """服务端以明细合计为准，避免客户端篡改或模型算术误差。"""
        self.total_amount = round(sum(item.amount for item in self.items), 2)
        return self


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
    today = business_date().isoformat()
    messages = [
        {
            "role": "system",
            "content": f"""你是报销单填写助手。从用户的自然语言描述中提取报销信息，生成结构化表单。
今天是 {today}。
规则：
1. 如果用户说"上周"，根据今天日期推算具体日期
2. 金额务必精确，提到"约""大概"时保留原数字
3. 如果描述中有金额超过单笔3000元的项目，在 warnings 里提示
4. 如果报销事由不明确，在 warnings 里提示需要补充
5. total_amount 等于所有 items 的 amount 之和

{_EXPENSE_SCHEMA}""",
        },
        {"role": "user", "content": text},
    ]
    return await parse_with_retry(model, messages, ExpenseForm)


# ── 请假申请 ────────────────────────────────────────────────


class LeaveForm(CamelModel):
    """请假单表单"""

    type: Literal["annual", "personal", "sick", "compensatory", "marriage", "maternity"] = Field(
        description="假期类型：annual=年假, personal=事假, sick=病假, compensatory=调休, marriage=婚假, maternity=产假"
    )
    start_date: DateType = Field(description="开始日期 YYYY-MM-DD")
    end_date: DateType = Field(description="结束日期 YYYY-MM-DD")
    days: float = Field(gt=0, description="请假天数（自然日）")
    workdays: float = Field(ge=0, description="工作日天数（排除周末）")
    reason: str = Field(min_length=1, max_length=300, description="请假原因")
    emergency_contact: Optional[str] = Field(default=None, max_length=128, description="紧急联系人")
    warnings: List[str] = Field(default_factory=list, description="异常或需要注意的地方（如需双重审批/证明材料）")

    @model_validator(mode="after")
    def validate_and_recompute_duration(self):
        """日期区间必须正向，天数由服务端统一重算。"""
        if self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        natural_days = (self.end_date - self.start_date).days + 1
        if natural_days > 366:
            raise ValueError("单次请假不能超过 366 天")
        self.days = float(natural_days)
        self.workdays = float(_count_workdays(self.start_date, self.end_date))
        return self


_LEAVE_SCHEMA = """返回纯 JSON，格式：
{"type": "annual"|"personal"|"sick"|"compensatory"|"marriage"|"maternity", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "days": float, "workdays": float, "reason": str, "emergency_contact": str|null, "warnings": [str]}"""


def _count_workdays(start_value, end_value):
    """
    计算两个日期之间的工作日数（排除周六周日）

    用于请假单的 workdays 字段
    """
    start = start_value if isinstance(start_value, DateType) else datetime.strptime(start_value, "%Y-%m-%d").date()
    end = end_value if isinstance(end_value, DateType) else datetime.strptime(end_value, "%Y-%m-%d").date()
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
    today = business_date().isoformat()
    messages = [
        {
            "role": "system",
            "content": f"""你是请假申请助手。从用户的自然语言描述中提取请假信息。
今天是 {today}。
规则：
1. "下周一到周三"等相对日期要换算成具体日期
2. days 是自然日（含周末），workdays 是工作日（不含周末）
3. 请假超过3个工作日时，在 warnings 里提示需要主管和 HR 双重审批
4. 病假要在 warnings 里提示需要提供医院证明
5. 产假/婚假要在 warnings 里提示需要提供相关证明材料

{_LEAVE_SCHEMA}""",
        },
        {"role": "user", "content": text},
    ]
    result = await parse_with_retry(model, messages, LeaveForm)

    return result
