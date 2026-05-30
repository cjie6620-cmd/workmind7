"""
Prompt 服务模块

提供 Prompt 模板管理和评分功能：
- list_templates: 获取模板列表
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
from ...utils.llm_parse import parse_with_retry

score_model = create_chat_model(temperature=0)

# ── 模板存储 ────────────────────────────────────────────────

# 内存存储模板（生产环境建议用数据库）
template_store = {}
_template_seq = 0

# 内置默认模板
default_templates = [
    {
        'id': 't_default_1',
        'name': '前端助手',
        'systemPrompt': '你是前端开发专家，精通 Vue3、React、TypeScript。回答简洁准确，必要时给代码示例。',
        'description': '通用前端技术问答',
        'tags': ['前端', '技术'],
        'createdAt': datetime.now().isoformat(),
        'versions': [],
    },
    {
        'id': 't_default_2',
        'name': '代码 Review',
        'systemPrompt': """你是资深代码评审专家。审查代码时，按以下顺序输出：
1. 【总体评价】一句话概括
2. 【问题列表】按严重程度排序，每条格式：[严重/一般/建议] 具体问题
3. 【优化建议】具体的改进代码示例
语气专业，直指问题，不废话。""",
        'description': '代码审查专用',
        'tags': ['代码', '审查'],
        'createdAt': datetime.now().isoformat(),
        'versions': [],
    },
    {
        'id': 't_default_3',
        'name': '简洁问答',
        'systemPrompt': '用最简洁的语言回答问题，不超过3句话，不用废话开场。',
        'description': '简短精准的回答风格',
        'tags': ['简洁'],
        'createdAt': datetime.now().isoformat(),
        'versions': [],
    },
]

for t in default_templates:
    template_store[t['id']] = t


def list_templates():
    """获取所有模板（按创建时间倒序）"""
    return sorted(template_store.values(), key=lambda t: t['createdAt'], reverse=True)


def get_template(template_id):
    """获取指定模板"""
    return template_store.get(template_id)


def save_template(name, system_prompt, description='', tags=None, existing_id=None):
    """
    创建或更新模板

    参数：
    - name: 模板名称
    - system_prompt: 提示词内容
    - description: 描述
    - tags: 标签
    - existing_id: 存在则更新，不存在则创建

    更新时会保存历史版本（最多保留 10 个）
    """
    global _template_seq
    tags = tags or []
    template_id = existing_id or f't_{int(datetime.now().timestamp() * 1000)}_{_template_seq}'
    _template_seq += 1

    existing = template_store.get(template_id)

    template = {
        'id': template_id,
        'name': name,
        'systemPrompt': system_prompt,
        'description': description,
        'tags': tags,
        'createdAt': existing['createdAt'] if existing else datetime.now().isoformat(),
        'updatedAt': datetime.now().isoformat(),
        # 保存历史版本
        'versions': [
            *(existing.get('versions', []) if existing else []),
            {
                'version': len(existing.get('versions', [])) + 1 if existing else 1,
                'systemPrompt': existing['systemPrompt'] if existing else system_prompt,
                'savedAt': datetime.now().isoformat(),
            },
        ][-10:],  # 最多保留 10 个版本
    }

    template_store[template_id] = template
    return template


def delete_template(template_id):
    """
    删除模板

    规则：
    - 内置模板（t_default_*）不可删除
    - 不存在的模板抛出异常
    """
    if template_id.startswith('t_default_'):
        raise ValueError('内置模板不能删除')
    if template_id not in template_store:
        raise ValueError('模板不存在')
    del template_store[template_id]


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