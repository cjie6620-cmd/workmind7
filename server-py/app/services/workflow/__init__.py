"""
Workflow 工作流模块

提供内容工作流功能：
- 四个内置工作流：周报、会议纪要、邮件润色、PRD 骨架
- 基于 LangGraph 状态机实现
- 支持人工审核节点（interrupt）
"""

from .workflows import WORKFLOW_BUILDERS, WORKFLOW_META

__all__ = ["WORKFLOW_BUILDERS", "WORKFLOW_META"]
