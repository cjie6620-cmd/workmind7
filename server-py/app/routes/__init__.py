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

# 路由由 app.main 显式注册。这里禁止 eager import 全部路由，否则任一服务在
# 导入监控模块时都会再次加载 agent/model，形成启动期循环依赖。
__all__: list[str] = []
