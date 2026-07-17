"""API 请求体 Pydantic 模型"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task: str = Field(..., min_length=1, max_length=2000)
    sessionId: Optional[str] = Field(default=None, max_length=128)
    configId: Optional[str] = Field(default=None, max_length=64)


class ChatFeedbackRequest(BaseModel):
    rating: Literal["helpful", "unhelpful"]


class KnowledgeQueryRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str = Field(..., min_length=1, max_length=2000)
    category: Optional[str] = Field(default=None, max_length=64)
    sessionId: Optional[str] = Field(default=None, max_length=128)


class WorkflowStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workflowId: str = Field(..., max_length=64)
    input: dict = Field(default_factory=dict)


class WorkflowResumeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    threadId: str = Field(..., max_length=128)
    feedback: str = Field(default="", max_length=2000)


class ErpParseRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text: str = Field(..., min_length=1, max_length=4000)
    formType: Literal["expense", "leave"]


class ErpSubmitRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    formType: Literal["expense", "leave"]
    formData: dict = Field(default_factory=dict)
    # applicantName 仅为旧客户端兼容字段，服务端始终使用认证用户姓名。
    applicantName: str = Field(default="申请人", max_length=64)
    sessionId: Optional[str] = Field(default=None, max_length=128)
    requestId: Optional[str] = Field(default=None, min_length=8, max_length=128)


class PromptTestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    systemPrompt: str = Field(default="", max_length=8000)
    userMessage: str = Field(..., min_length=1, max_length=4000)
    temperature: float = Field(default=0.7, ge=0, le=2)
    maxTokens: int = Field(default=1000, ge=1, le=32000)


class PromptAbTestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str = Field(..., min_length=1, max_length=2000)
    systemPromptA: str = Field(default="", max_length=8000)
    systemPromptB: str = Field(default="", max_length=8000)
    temperature: float = Field(default=0, ge=0, le=2)
    maxTokens: int = Field(default=800, ge=1, le=32000)


class PromptTemplateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=128)
    systemPrompt: str = Field(..., min_length=1, max_length=8000)
    description: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list)


class ConfigCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    configType: Literal["agent", "workflow", "prompt"]
    name: str = Field(..., min_length=1, max_length=128)
    configJson: dict = Field(default_factory=dict)


class ConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(default=None, max_length=128)
    configJson: Optional[dict] = None
    expectedVersion: Optional[int] = Field(
        default=None,
        ge=1,
        description="乐观锁版本；传入时与当前 version 不一致则返回冲突",
    )


class BudgetUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dailyBudget: float = Field(..., gt=0, le=1000000)
