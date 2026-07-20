"""
配置中心路由模块

统一管理 Agent、Workflow、Prompt 三类配置的 CRUD：
- GET  /           按类型查列表（?type=prompt）
- GET  /{id}       获取单条配置
- POST /           创建配置
- PUT  /{id}       更新配置
- DELETE /{id}     删除配置
- POST /{id}/activate    启用
- POST /{id}/deactivate  停用
"""

from fastapi import APIRouter, Query

from ..services.config.config_service import (
    list_configs,
    get_config,
    create_config,
    update_config,
    delete_config,
    toggle_active,
)
from ..services.config.validation import validate_config_payload
from ..schemas.requests import ConfigCreateRequest, ConfigUpdateRequest
from ..utils.responses import error_response

config_router = APIRouter()


@config_router.get("")
async def list_configs_api(config_type: str = Query(None, alias="type")):
    """按类型查询配置列表"""
    if not config_type:
        return error_response(400, "缺少 type 参数")
    if config_type not in ("prompt", "agent", "workflow"):
        return error_response(400, f"不支持的配置类型：{config_type}")
    configs = await list_configs(config_type)
    return {"configs": configs}


@config_router.get("/{config_id}")
async def get_config_api(config_id: str):
    """获取单条配置详情"""
    config = await get_config(config_id)
    if not config:
        return error_response(404, "配置不存在")
    return config


@config_router.post("/")
async def create_config_api(req: ConfigCreateRequest):
    """创建配置"""
    try:
        validate_config_payload(req.configType, req.name, req.configJson)
        config = await create_config(req.configType, req.name, req.configJson)
        return {"success": True, "config": config}
    except ValueError as err:
        return error_response(400, str(err))


@config_router.put("/{config_id}")
async def update_config_api(config_id: str, req: ConfigUpdateRequest):
    """更新配置"""
    try:
        existing = await get_config(config_id)
        if not existing:
            return error_response(404, "配置不存在")
        next_name = req.name if req.name is not None else existing["name"]
        next_json = req.configJson if req.configJson is not None else existing["configJson"]
        validate_config_payload(existing["configType"], next_name, next_json)
        config = await update_config(
            config_id,
            name=req.name,
            config_json=req.configJson,
            expected_version=req.expectedVersion,
        )
        return {"success": True, "config": config}
    except ValueError as err:
        message = str(err)
        status = 409 if "已被其他请求更新" in message else 400
        return error_response(status, message)


@config_router.delete("/{config_id}")
async def delete_config_api(config_id: str):
    """删除配置"""
    try:
        await delete_config(config_id)
        return {"success": True}
    except ValueError as err:
        return error_response(400, str(err))


@config_router.post("/{config_id}/activate")
async def activate_config_api(config_id: str):
    """启用配置"""
    try:
        config = await toggle_active(config_id, True)
        return {"success": True, "config": config}
    except ValueError as err:
        return error_response(400, str(err))


@config_router.post("/{config_id}/deactivate")
async def deactivate_config_api(config_id: str):
    """停用配置"""
    try:
        config = await toggle_active(config_id, False)
        return {"success": True, "config": config}
    except ValueError as err:
        return error_response(400, str(err))
