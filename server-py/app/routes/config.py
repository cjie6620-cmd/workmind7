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

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..services.config.config_service import (
    list_configs, get_config, create_config,
    update_config, delete_config, toggle_active,
)
from ..utils.logger import logger

config_router = APIRouter()


@config_router.get('/')
async def list_configs_api(type: str = None):
    """按类型查询配置列表"""
    if not type:
        return JSONResponse(status_code=400, content={'error': {'message': '缺少 type 参数'}})
    if type not in ('prompt', 'agent', 'workflow'):
        return JSONResponse(status_code=400, content={'error': {'message': f'不支持的配置类型：{type}'}})
    configs = await list_configs(type)
    return {'configs': configs}


@config_router.get('/{config_id}')
async def get_config_api(config_id: str):
    """获取单条配置详情"""
    config = await get_config(config_id)
    if not config:
        return JSONResponse(status_code=404, content={'error': {'message': '配置不存在'}})
    return config


@config_router.post('/')
async def create_config_api(req: dict):
    """创建配置"""
    config_type = (req.get('configType') or '').strip()
    name = (req.get('name') or '').strip()
    config_json = req.get('configJson')

    if not config_type or not name:
        return JSONResponse(status_code=400, content={'error': {'message': '类型和名称不能为空'}})
    if not config_json:
        return JSONResponse(status_code=400, content={'error': {'message': '配置内容不能为空'}})

    try:
        config = await create_config(config_type, name, config_json)
        return {'success': True, 'config': config}
    except ValueError as err:
        return JSONResponse(status_code=400, content={'error': {'message': str(err)}})


@config_router.put('/{config_id}')
async def update_config_api(config_id: str, req: dict):
    """更新配置"""
    try:
        config = await update_config(
            config_id,
            name=req.get('name'),
            config_json=req.get('configJson'),
        )
        return {'success': True, 'config': config}
    except ValueError as err:
        return JSONResponse(status_code=400, content={'error': {'message': str(err)}})


@config_router.delete('/{config_id}')
async def delete_config_api(config_id: str):
    """删除配置"""
    try:
        await delete_config(config_id)
        return {'success': True}
    except ValueError as err:
        return JSONResponse(status_code=400, content={'error': {'message': str(err)}})


@config_router.post('/{config_id}/activate')
async def activate_config_api(config_id: str):
    """启用配置"""
    try:
        config = await toggle_active(config_id, True)
        return {'success': True, 'config': config}
    except ValueError as err:
        return JSONResponse(status_code=400, content={'error': {'message': str(err)}})


@config_router.post('/{config_id}/deactivate')
async def deactivate_config_api(config_id: str):
    """停用配置"""
    try:
        config = await toggle_active(config_id, False)
        return {'success': True, 'config': config}
    except ValueError as err:
        return JSONResponse(status_code=400, content={'error': {'message': str(err)}})
