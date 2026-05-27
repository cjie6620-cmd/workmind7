"""
Services 服务层模块

业务逻辑层，处理核心功能和算法：
- model: 模型工厂（对话模型 + 向量化模型，均为延迟加载）
- cache: 精确缓存，避免重复调用
- agent: 任务 Agent（ReAct 模式）
- chat: 会话管理与用户画像
- erp: 表单解析与 Multi-Agent 审批
- prompt: Prompt 模板管理与评分
- rag: 知识库 RAG（文档入库 + 向量查询）
- workflow: 内容工作流（周报/会议纪要/邮件/PRD）
"""

from .model import get_chat_model, create_chat_model, get_embeddings
from .cache import cache

__all__ = [
    'get_chat_model',
    'create_chat_model',
    'get_embeddings',
    'cache',
]