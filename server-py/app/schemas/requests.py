"""API 请求体 Pydantic 模型（字段命名与前端契约保持 camelCase）"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    """对话流式接口请求体"""

    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(..., min_length=1, max_length=4000, description="用户消息内容")
    sessionId: str = Field(default="default", alias="session_id", description="会话 ID；default 表示新建会话")
    systemPrompt: str = Field(
        default="", max_length=2000, alias="system_prompt", description="自定义系统提示词（可选）"
    )
    role: str = Field(default="default", description="预设角色 ID，决定系统提示词模板")

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v):
        if not v.strip():
            raise ValueError("消息不能为空")
        return v


class AgentRunRequest(BaseModel):
    """Agent 任务提交请求体"""

    model_config = ConfigDict(populate_by_name=True)

    task: str = Field(..., min_length=1, max_length=2000, description="任务描述（自然语言）")
    sessionId: Optional[str] = Field(default=None, max_length=128, description="会话 ID；空则服务端生成")
    configId: Optional[str] = Field(default=None, max_length=64, description="已发布的 Agent 配置 ID（可选）")


class ChatFeedbackRequest(BaseModel):
    """消息点赞/点踩反馈"""

    rating: Literal["helpful", "unhelpful"] = Field(description="反馈评价：有帮助 / 无帮助")


class KnowledgeQueryRequest(BaseModel):
    """知识库 RAG 问答请求体"""

    model_config = ConfigDict(populate_by_name=True)

    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    category: Optional[str] = Field(default=None, max_length=64, description="限定检索的文档分类（可选）")
    sessionId: Optional[str] = Field(default=None, max_length=128, description="会话 ID；空则服务端生成")


class WorkflowStartRequest(BaseModel):
    """工作流启动请求体"""

    model_config = ConfigDict(populate_by_name=True)

    workflowId: str = Field(..., max_length=64, description="工作流模板 ID（weekly_report 等）")
    input: dict = Field(default_factory=dict, description="工作流输入字段，按模板 schema 校验")


class WorkflowResumeRequest(BaseModel):
    """工作流人工审核后恢复请求体"""

    model_config = ConfigDict(populate_by_name=True)

    threadId: str = Field(..., max_length=128, description="启动时返回的运行线程 ID")
    feedback: str = Field(default="", max_length=2000, description="人工审核意见，注入后续生成节点")


class ErpParseRequest(BaseModel):
    """ERP 自然语言填单解析请求体"""

    model_config = ConfigDict(populate_by_name=True)

    text: str = Field(..., min_length=1, max_length=4000, description="自然语言描述（如「出差3天报销机票1200元」）")
    formType: Literal["expense", "leave"] = Field(description="表单类型：报销 / 请假")


class ErpSubmitRequest(BaseModel):
    """ERP AI 预审提交请求体"""

    model_config = ConfigDict(populate_by_name=True)

    formType: Literal["expense", "leave"] = Field(description="表单类型：报销 / 请假")
    formData: dict = Field(default_factory=dict, description="表单字段；金额/工作日由服务端重算校验")
    # applicantName 仅为旧客户端兼容字段，服务端始终使用认证用户姓名。
    applicantName: str = Field(default="申请人", max_length=64, description="兼容字段，服务端忽略并覆盖为认证用户名")
    sessionId: Optional[str] = Field(default=None, max_length=128, description="会话 ID（未传 requestId 时兼作幂等键）")
    requestId: Optional[str] = Field(
        default=None, min_length=8, max_length=128, description="客户端幂等请求 ID，防重复提交"
    )


class PromptTestRequest(BaseModel):
    """Prompt 单次调试请求体"""

    model_config = ConfigDict(populate_by_name=True)

    systemPrompt: str = Field(default="", max_length=8000, description="待调试的系统提示词")
    userMessage: str = Field(..., min_length=1, max_length=4000, description="模拟的用户输入")
    temperature: float = Field(default=0.7, ge=0, le=2, description="采样温度")
    maxTokens: int = Field(default=1000, ge=1, le=32000, description="输出 token 上限")


class PromptAbTestRequest(BaseModel):
    """Prompt A/B 对比测试请求体（双流并行生成 + LLM 评分）"""

    model_config = ConfigDict(populate_by_name=True)

    question: str = Field(..., min_length=1, max_length=2000, description="两侧共用的测试问题")
    systemPromptA: str = Field(default="", max_length=8000, description="A 侧系统提示词")
    systemPromptB: str = Field(default="", max_length=8000, description="B 侧系统提示词")
    temperature: float = Field(default=0, ge=0, le=2, description="采样温度（0 保证对比可复现）")
    maxTokens: int = Field(default=800, ge=1, le=32000, description="单侧输出 token 上限")


class PromptTemplateRequest(BaseModel):
    """Prompt 模板创建/更新请求体"""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=128, description="模板名称（全局唯一）")
    systemPrompt: str = Field(..., min_length=1, max_length=8000, description="系统提示词正文")
    description: str = Field(default="", max_length=500, description="模板用途说明")
    tags: list[str] = Field(default_factory=list, description="分类标签")


class ConfigCreateRequest(BaseModel):
    """配置中心创建请求体"""

    model_config = ConfigDict(populate_by_name=True)

    configType: Literal["agent", "workflow", "prompt"] = Field(description="配置类型")
    name: str = Field(..., min_length=1, max_length=128, description="配置名称（全局唯一）")
    configJson: dict = Field(default_factory=dict, description="配置内容，按类型走 validation 校验")


class ConfigUpdateRequest(BaseModel):
    """配置中心更新请求体（支持乐观并发控制）"""

    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(default=None, max_length=128, description="新名称（不传则不改）")
    configJson: Optional[dict] = Field(default=None, description="新配置内容（不传则不改）")
    expectedVersion: Optional[int] = Field(
        default=None,
        ge=1,
        description="乐观锁版本；传入时与当前 version 不一致则返回冲突",
    )


class BudgetUpdateRequest(BaseModel):
    """日预算设置请求体"""

    model_config = ConfigDict(populate_by_name=True)

    dailyBudget: float = Field(..., gt=0, le=1000000, description="日预算上限（人民币元）")
