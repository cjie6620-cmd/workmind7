"""
Golden Dataset 辅助生成工具

从测试文档中自动生成 QA 评测对，辅助构建 golden_dataset.json。
生成的 QA 对需人工审核后才能入库。

用法：
    python scripts/generate_golden_dataset.py
    python scripts/generate_golden_dataset.py --output tests/fixtures/golden_dataset_auto.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

# 第一步：将 server-py 加入 sys.path
SERVER_PY = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SERVER_PY)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / 'tests' / 'fixtures'
SAMPLE_DOCS_DIR = FIXTURES_DIR / 'sample_documents'


def load_documents():
    """加载测试文档"""
    docs = {}
    for file_path in SAMPLE_DOCS_DIR.iterdir():
        if file_path.suffix in ('.txt', '.md'):
            with open(file_path, 'r', encoding='utf-8') as f:
                docs[file_path.name] = f.read()
    return docs


def extract_facts(text: str, doc_name: str) -> list:
    """
    从文本中提取事实段落

    简化实现：按句子拆分，过滤掉太短的句子。
    实际项目中可用 LLM 生成更丰富的 QA 对。
    """
    facts = []
    # 按中文句号拆分
    sentences = []
    for paragraph in text.split('\n'):
        paragraph = paragraph.strip()
        if not paragraph or paragraph.startswith('#'):
            continue
        for sentence in paragraph.split('。'):
            sentence = sentence.strip()
            if len(sentence) > 10:
                sentences.append(sentence + '。')

    return sentences


def generate_qa_pairs(doc_name: str, text: str, category: str) -> list:
    """
    基于规则生成 QA 对

    实际项目中应使用 DeepSeek API 生成更高质量的 QA 对。
    这里用规则匹配演示流程。
    """
    qa_pairs = []

    # 规则模板：从文本中提取数字型事实
    import re
    number_patterns = re.findall(r'([\u4e00-\u9fa5]+)[为是]?\s*(\d+[\.\d]*)\s*([\u4e00-\u9fa5%天元人次]+)', text)

    for i, (context, number, unit) in enumerate(number_patterns):
        question = f"{context}是多少{unit.strip('天元人次')}？"
        answer = f"{context}{number}{unit}"

        qa_pairs.append({
            'id': f'auto_{doc_name}_{i:03d}',
            'user_input': question,
            'category': category,
            'query_type': 'single_hop_specific',
            'expected_source_titles': [doc_name],
            'expected_source_chunk_keywords': [context, number],
            'reference': answer,
            'difficulty': 'easy',
        })

    return qa_pairs


def main():
    parser = argparse.ArgumentParser(description='Golden Dataset 辅助生成')
    parser.add_argument('--output', default=str(FIXTURES_DIR / 'golden_dataset_auto.json'),
                        help='输出文件路径')
    parser.add_argument('--max-per-doc', type=int, default=15,
                        help='每份文档最多生成 QA 对数')

    args = parser.parse_args()

    docs = load_documents()
    print(f'加载了 {len(docs)} 份文档: {list(docs.keys())}')

    category_map = {
        '公司规章制度.txt': 'HR制度',
        '差旅报销规定.txt': '财务',
        '产品介绍.md': '产品手册',
        '技术架构说明.md': '技术文档',
    }

    all_qa = []

    for doc_name, text in docs.items():
        category = category_map.get(doc_name, '通用')
        qa_pairs = generate_qa_pairs(doc_name, text, category)

        # 限制每份文档的数量
        qa_pairs = qa_pairs[:args.max_per_doc]
        all_qa.extend(qa_pairs)

        print(f'  {doc_name} ({category}): 生成 {len(qa_pairs)} 条 QA')

    # 输出
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_qa, f, ensure_ascii=False, indent=2)

    print(f'\n共生成 {len(all_qa)} 条 QA 对')
    print(f'已保存到: {output_path}')
    print('\n⚠ 注意：自动生成的 QA 对需人工审核后才能用于评测！')


if __name__ == '__main__':
    main()
