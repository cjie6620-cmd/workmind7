"""
Routes 路由层模块

定义所有 API 路由，包括：
- health: 健康检查
- chat: 智能对话
- knowledge: 知识库管理
- agent: 任务 Agent
- workflow: 内容工作流
- erp: ERP 审批流
- prompt: Prompt 调试
- monitor: 用量监控
"""

from .health import health_router
from .chat import chat_router
from .knowledge import knowledge_router
from .agent import agent_router
from .workflow import workflow_router
from .erp import erp_router
from .prompt import prompt_router
from .monitor import monitor_router

__all__ = [
    'health_router',
    'chat_router',
    'knowledge_router',
    'agent_router',
    'workflow_router',
    'erp_router',
    'prompt_router',
    'monitor_router',
]