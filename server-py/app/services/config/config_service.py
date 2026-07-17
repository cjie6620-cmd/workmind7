"""
配置中心服务模块

统一管理 Agent、Workflow、Prompt 三类配置，
操作 agent_configs 表，按 config_type 区分。
"""

from typing import Optional

from sqlalchemy import select, delete as sa_delete

from ...core.database import async_session_factory
from ...models.entities import AgentConfig
from ...utils.business_time import utc_now_naive
from ...utils.logger import logger

# 不允许通过配置接口删除的类型
PROTECTED_TYPES = {"profile"}


async def list_configs(config_type: str) -> list[dict]:
    """按类型查询配置列表，按 updated_at 倒序"""
    async with async_session_factory() as session:
        result = await session.execute(
            select(AgentConfig).where(AgentConfig.config_type == config_type).order_by(AgentConfig.updated_at.desc())
        )
        rows = result.scalars().all()

    return [_to_dict(row) for row in rows]


async def get_config(config_id: str) -> Optional[dict]:
    """获取单条配置"""
    async with async_session_factory() as session:
        result = await session.execute(select(AgentConfig).where(AgentConfig.id == config_id))
        row = result.scalar_one_or_none()

    if not row:
        return None
    return _to_dict(row)


async def create_config(config_type: str, name: str, config_json: dict) -> dict:
    """
    创建配置

    校验 name 唯一性，创建新配置记录
    """
    async with async_session_factory() as session:
        # 名称唯一性校验
        existing = await session.execute(select(AgentConfig).where(AgentConfig.name == name))
        if existing.scalar_one_or_none():
            raise ValueError(f"配置名称「{name}」已存在")

        config = AgentConfig(
            config_type=config_type,
            name=name,
            config_json=config_json,
        )
        session.add(config)
        await session.commit()
        # 刷新获取生成的 id 和时间戳
        await session.refresh(config)

    return _to_dict(config)


async def update_config(
    config_id: str,
    *,
    name: str | None = None,
    config_json: dict | None = None,
    expected_version: int | None = None,
) -> dict:
    """
    更新配置

    自动 version+1，支持更新名称和配置内容
    """
    async with async_session_factory() as session:
        result = await session.execute(select(AgentConfig).where(AgentConfig.id == config_id).with_for_update())
        config = result.scalar_one_or_none()
        if not config:
            raise ValueError("配置不存在")
        if expected_version is not None and config.version != expected_version:
            raise ValueError("配置已被其他请求更新，请刷新后重试")

        # 名称唯一性校验（排除自身）
        if name and name != config.name:
            dup = await session.execute(select(AgentConfig).where(AgentConfig.name == name))
            if dup.scalar_one_or_none():
                raise ValueError(f"配置名称「{name}」已存在")
            config.name = name

        if config_json is not None:
            config.config_json = config_json

        config.version += 1
        config.updated_at = utc_now_naive()
        await session.commit()
        await session.refresh(config)

    return _to_dict(config)


async def delete_config(config_id: str) -> bool:
    """
    删除配置

    profile 类型不允许删除
    """
    async with async_session_factory() as session:
        result = await session.execute(select(AgentConfig).where(AgentConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise ValueError("配置不存在")
        if config.config_type in PROTECTED_TYPES:
            raise ValueError(f"{config.config_type} 类型配置不允许删除")

        await session.execute(sa_delete(AgentConfig).where(AgentConfig.id == config_id))
        await session.commit()

    return True


async def toggle_active(config_id: str, active: bool) -> dict:
    """切换配置启用/停用状态"""
    async with async_session_factory() as session:
        result = await session.execute(select(AgentConfig).where(AgentConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise ValueError("配置不存在")

        config.is_active = active
        await session.commit()
        await session.refresh(config)

    return _to_dict(config)


async def seed_if_empty(config_type: str, seeds: list[dict]) -> int:
    """
    种子数据：仅当指定类型的配置为空时插入

    seeds 格式：[{ name, config_json }, ...]
    返回实际插入的条数
    """
    async with async_session_factory() as session:
        result = await session.execute(select(AgentConfig).where(AgentConfig.config_type == config_type))
        if result.scalars().first():
            return 0

        count = 0
        for seed in seeds:
            config = AgentConfig(
                config_type=config_type,
                name=seed["name"],
                config_json=seed["config_json"],
            )
            session.add(config)
            count += 1

        await session.commit()

    logger.info(f"seeded {count} configs for type={config_type}")
    return count


# ── 内部工具 ──────────────────────────────────────────────────


def _to_dict(row: AgentConfig) -> dict:
    """将 ORM 对象转为前端友好的字典"""
    return {
        "id": str(row.id),
        "configType": row.config_type,
        "name": row.name,
        "configJson": row.config_json,
        "version": row.version,
        "isActive": row.is_active,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }
