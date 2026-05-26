# Prompt 调试：模板管理、A/B 测试评分
import json
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage

from ..model import create_chat_model

score_model = create_chat_model(temperature=0)

# ── 模板存储 ────────────────────────────────────────────────

template_store = {}
_template_seq = 0

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
    return sorted(template_store.values(), key=lambda t: t['createdAt'], reverse=True)


def get_template(template_id):
    return template_store.get(template_id)


def save_template(name, system_prompt, description='', tags=None, existing_id=None):
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
        'versions': [
            *(existing.get('versions', []) if existing else []),
            {
                'version': len(existing.get('versions', [])) + 1 if existing else 1,
                'systemPrompt': existing['systemPrompt'] if existing else system_prompt,
                'savedAt': datetime.now().isoformat(),
            },
        ][-10:],
    }

    template_store[template_id] = template
    return template


def delete_template(template_id):
    if template_id.startswith('t_default_'):
        raise ValueError('内置模板不能删除')
    if template_id not in template_store:
        raise ValueError('模板不存在')
    del template_store[template_id]


# ── A/B 评分 ────────────────────────────────────────────────

class EvalResult(BaseModel):
    relevance: int = Field(ge=1, le=5, description='回答与问题的相关性')
    accuracy: int = Field(ge=1, le=5, description='内容的准确性')
    clarity: int = Field(ge=1, le=5, description='表达的清晰度')
    conciseness: int = Field(ge=1, le=5, description='是否简洁')
    overall: int = Field(ge=1, le=5, description='综合评分')
    winner: Literal['A', 'B', 'tie'] = 'tie'
    reason: str = Field(description='判断理由，一句话')


class Comparison(BaseModel):
    winner: Literal['A', 'B', 'tie'] = 'tie'
    reason: str = Field(description='对比理由，30字以内')


async def score_ab_test(question, answer_a, answer_b):
    eval_model = score_model.with_structured_output(EvalResult)

    eval_a, eval_b = await eval_model.ainvoke([
        SystemMessage('你是 AI 回答质量评估专家，客观评分，不偏袒任何一方。'),
        HumanMessage(f'问题：{question}\n\n回答：{answer_a}'),
    ]), await eval_model.ainvoke([
        SystemMessage('你是 AI 回答质量评估专家，客观评分，不偏袒任何一方。'),
        HumanMessage(f'问题：{question}\n\n回答：{answer_b}'),
    ])

    compare_model = score_model.with_structured_output(Comparison)
    comparison = await compare_model.ainvoke([
        SystemMessage('比较两个回答，选出更好的那个。评分相差0.5分以内视为平局。'),
        HumanMessage(f"""问题：{question}

回答A：{answer_a}
A的评分：相关性{eval_a.relevance} 准确性{eval_a.accuracy} 清晰度{eval_a.clarity} 简洁性{eval_a.conciseness} 综合{eval_a.overall}

回答B：{answer_b}
B的评分：相关性{eval_b.relevance} 准确性{eval_b.accuracy} 清晰度{eval_b.clarity} 简洁性{eval_b.conciseness} 综合{eval_b.overall}

哪个回答更好？"""),
    ])

    return {
        'scoreA': eval_a.model_dump(),
        'scoreB': eval_b.model_dump(),
        'winner': comparison.winner,
        'reason': comparison.reason,
    }
