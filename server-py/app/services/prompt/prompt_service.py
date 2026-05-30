"""
Prompt 服务模块

提供 Prompt 模板管理和评分功能：
- list_templates: 获取模板列表（从数据库）
- get_template: 获取模板详情
- save_template: 创建/更新模板（含版本管理）
- delete_template: 删除模板
- score_ab_test: A/B 测试评分
"""

import asyncio
from datetime import datetime
from typing import List, Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..model import create_chat_model
from ..config.config_service import (
    list_configs as db_list,
    get_config as db_get,
    create_config as db_create,
    update_config as db_update,
    delete_config as db_delete,
)
from ...utils.llm_parse import parse_with_retry

score_model = create_chat_model(temperature=0)


# ── 模板 CRUD（数据库存储）───────────────────────────────────

async def list_templates() -> list[dict]:
    """获取所有 Prompt 模板（从数据库，按更新时间倒序）"""
    configs = await db_list('prompt')
    # 转换为前端兼容的模板格式
    templates = []
    for c in configs:
        cj = c['configJson']
        templates.append({
            'id': c['id'],
            'name': c['name'],
            'systemPrompt': cj.get('systemPrompt', ''),
            'description': cj.get('description', ''),
            'tags': cj.get('tags', []),
            'createdAt': c['createdAt'],
            'updatedAt': c['updatedAt'],
            'versions': cj.get('versions', []),
        })
    return templates


async def get_template(template_id: str) -> Optional[dict]:
    """获取指定模板"""
    c = await db_get(template_id)
    if not c or c['configType'] != 'prompt':
        return None
    cj = c['configJson']
    return {
        'id': c['id'],
        'name': c['name'],
        'systemPrompt': cj.get('systemPrompt', ''),
        'description': cj.get('description', ''),
        'tags': cj.get('tags', []),
        'createdAt': c['createdAt'],
        'updatedAt': c['updatedAt'],
        'versions': cj.get('versions', []),
    }


async def save_template(name: str, system_prompt: str, description: str = '', tags: list = None, existing_id: str = None) -> dict:
    """
    创建或更新模板

    更新时自动保存历史版本（最多保留 10 个）
    """
    tags = tags or []

    if existing_id:
        # 更新：先获取现有数据，追加版本历史
        existing = await db_get(existing_id)
        if not existing:
            raise ValueError('模板不存在')

        old_cj = existing['configJson']
        old_versions = old_cj.get('versions', [])

        # 追加版本历史
        new_versions = [
            *old_versions,
            {
                'version': len(old_versions) + 1,
                'systemPrompt': old_cj.get('systemPrompt', ''),
                'savedAt': datetime.now().isoformat(),
            },
        ][-10:]  # 最多保留 10 个版本

        config_json = {
            'systemPrompt': system_prompt,
            'description': description,
            'tags': tags,
            'versions': new_versions,
        }
        result = await db_update(existing_id, name=name, config_json=config_json)
    else:
        # 新建
        config_json = {
            'systemPrompt': system_prompt,
            'description': description,
            'tags': tags,
            'versions': [],
        }
        result = await db_create('prompt', name, config_json)

    # 转换为前端兼容格式
    cj = result['configJson']
    return {
        'id': result['id'],
        'name': result['name'],
        'systemPrompt': cj.get('systemPrompt', ''),
        'description': cj.get('description', ''),
        'tags': cj.get('tags', []),
        'createdAt': result['createdAt'],
        'updatedAt': result['updatedAt'],
        'versions': cj.get('versions', []),
    }


async def delete_template(template_id: str):
    """删除模板"""
    await db_delete(template_id)


# ── A/B 评分 ────────────────────────────────────────────────

class ScoreResult(BaseModel):
    """单个回答评分结果"""
    relevance: int
    accuracy: int
    clarity: int
    conciseness: int
    overall: int
    winner: Literal['A', 'B', 'tie']
    reason: str


class CompareResult(BaseModel):
    """A/B 比较结果"""
    winner: Literal['A', 'B', 'tie']
    reason: str


async def score_ab_test(question, answer_a, answer_b):
    """
    A/B 测试评分

    流程：
    1. 分别评估 A、B 回答的质量（相关性、准确性、清晰度、简洁性）
    2. 综合比较两个回答，选出获胜者
    """
    eval_prompt = """你是 AI 回答质量评估专家，客观评分，不偏袒任何一方。
从以下维度评分（1-5分）：
- relevance: 回答与问题的相关性
- accuracy: 内容的准确性
- clarity: 表达的清晰度
- conciseness: 是否简洁
- overall: 综合评分
- winner: "A"|"B"|"tie"
- reason: 判断理由，一句话

返回纯 JSON：
{"relevance": int, "accuracy": int, "clarity": int, "conciseness": int, "overall": int, "winner": "A"|"B"|"tie", "reason": str}"""

    # 并行评估两个回答
    eval_a, eval_b = await asyncio.gather(
        parse_with_retry(
            score_model,
            [SystemMessage(eval_prompt), HumanMessage(f'问题：{question}\n\n回答：{answer_a}')],
            ScoreResult,
        ),
        parse_with_retry(
            score_model,
            [SystemMessage(eval_prompt), HumanMessage(f'问题：{question}\n\n回答：{answer_b}')],
            ScoreResult,
        ),
    )

    # 综合比较
    compare_prompt = """比较两个回答，选出更好的那个。评分相差0.5分以内视为平局。
返回纯 JSON：
{"winner": "A"|"B"|"tie", "reason": str}"""

    comparison = await parse_with_retry(
        score_model,
        [
            SystemMessage(compare_prompt),
            HumanMessage(f"""问题：{question}

回答A：{answer_a}
A的评分：相关性{eval_a.relevance} 准确性{eval_a.accuracy} 清晰度{eval_a.clarity} 简洁性{eval_a.conciseness} 综合{eval_a.overall}

回答B：{answer_b}
B的评分：相关性{eval_b.relevance} 准确性{eval_b.accuracy} 清晰度{eval_b.clarity} 简洁性{eval_b.conciseness} 综合{eval_b.overall}

哪个回答更好？"""),
        ],
        CompareResult,
    )

    return {
        'scoreA': eval_a.model_dump(),
        'scoreB': eval_b.model_dump(),
        'winner': comparison.winner,
        'reason': comparison.reason,
    }
