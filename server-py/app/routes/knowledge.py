"""
知识库路由模块

提供文档管理和 RAG 问答功能：
- POST /documents: 上传文档（支持文件或文本内容）
- GET /documents: 获取文档列表（支持分类筛选）
- DELETE /documents/{doc_id}: 删除文档
- POST /query/stream: RAG 流式问答
- GET /categories: 获取文档分类列表

注意：不使用 FastAPI 的 UploadFile/File/Form 解析 multipart，
因为 python-multipart 与 torch 存在段错误冲突。
改为手动解析 multipart/form-data。
"""

import json
import os
import re
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from ..services.rag.ingest import ingest_document, get_doc_registry, delete_document
from ..services.rag.query import rag_query_stream
from ..utils.sse import sse_event, sse_error
from ..utils.file_validate import validate_file, validate_ext, MAX_FILE_SIZE
from ..utils.logger import logger

knowledge_router = APIRouter()

# 文件上传目录
UPLOAD_DIR = './uploads'
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _safe_file_name(filename):
    name = (filename or '').replace('\\', '/').split('/')[-1].strip()
    name = re.sub(r'[^\w.\-一-鿿]+', '_', name)
    return name or f'upload_{int(time.time() * 1000)}.txt'


def _remove_file(path):
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _parse_multipart_boundary(content_type):
    for part in content_type.split(';'):
        part = part.strip()
        if part.startswith('boundary='):
            return part[len('boundary='):]
    return None


async def _read_multipart(request):
    """
    手动解析 multipart/form-data，避免 python-multipart 与 torch 的段错误冲突。
    仅提取第一个文件字段和普通字段。
    """
    content_type = request.headers.get('content-type', '')
    boundary = _parse_multipart_boundary(content_type)
    if not boundary:
        return {}, None

    body = await request.body()
    delimiter = b'--' + boundary.encode()

    fields = {}
    file_data = None

    parts = body.split(delimiter)
    for part in parts:
        if not part or part.strip() in (b'', b'--'):
            continue
        if b'\r\n\r\n' not in part:
            continue
        header_section, content = part.split(b'\r\n\r\n', 1)
        content = content.rstrip(b'\r\n')
        if content.endswith(b'--'):
            content = content[:-2]

        header_str = header_section.decode('utf-8', errors='replace')
        name_match = re.search(r'name="([^"]*)"', header_str)
        filename_match = re.search(r'filename="([^"]*)"', header_str)

        if not name_match:
            continue
        name = name_match.group(1)

        if filename_match:
            file_data = {
                'filename': filename_match.group(1),
                'content': content,
            }
        else:
            fields[name] = content.decode('utf-8', errors='replace')

    return fields, file_data


@knowledge_router.post('/documents')
async def upload_document(request: Request):
    """
    上传文档接口

    第一步：解析请求体（multipart 文件 或 JSON 文本）
    第二步：校验文件大小、扩展名、内容安全性
    第三步：写入临时文件，调用 ingest 向量化入库
    第四步：清理临时文件，返回文档元信息
    """
    file_path = None
    try:
        content_type = request.headers.get('content-type', '')

        if 'multipart/form-data' in content_type:
            fields, file_data = await _read_multipart(request)
            title = fields.get('title') or '未命名文档'
            category = fields.get('category') or '通用'

            if not file_data:
                return JSONResponse(
                    status_code=400,
                    content={'error': {'message': '请上传文件或提供文本内容'}},
                )

            original_name = _safe_file_name(file_data['filename'])
            file_content = file_data['content']

            if len(file_content) > MAX_FILE_SIZE:
                return JSONResponse(
                    status_code=400,
                    content={'error': {'message': '文件不能超过 10MB'}},
                )

            try:
                validate_ext(original_name)
            except ValueError as err:
                return JSONResponse(status_code=400, content={'error': {'message': str(err)}})

            safe_name = f'{uuid.uuid4().hex}_{original_name}'
            file_path = os.path.join(UPLOAD_DIR, safe_name)
            with open(file_path, 'wb') as f:
                f.write(file_content)

            try:
                validate_file(file_path, original_name)
            except ValueError as err:
                _remove_file(file_path)
                return JSONResponse(status_code=400, content={'error': {'message': str(err)}})

            doc_meta = await ingest_document(
                file_path=file_path,
                file_name=original_name,
                title=title or os.path.splitext(original_name)[0],
                category=category,
            )

        elif 'application/json' in content_type:
            try:
                payload = await request.json()
            except json.JSONDecodeError:
                return JSONResponse(status_code=400, content={'error': {'message': 'JSON 格式不正确'}})

            title = payload.get('title', '未命名文档')
            category = payload.get('category', '通用')
            content = payload.get('content')

            if not content:
                return JSONResponse(
                    status_code=400,
                    content={'error': {'message': '请上传文件或提供文本内容'}},
                )

            if len(content.encode('utf-8')) > MAX_FILE_SIZE:
                return JSONResponse(
                    status_code=400,
                    content={'error': {'message': '文本内容不能超过 10MB'}},
                )

            file_path = os.path.join(UPLOAD_DIR, f'tmp_{uuid.uuid4().hex}.txt')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            doc_meta = await ingest_document(
                file_path=file_path,
                file_name=(title or '文本内容') + '.txt',
                title=title,
                category=category,
            )
        else:
            return JSONResponse(
                status_code=400,
                content={'error': {'message': '不支持的 Content-Type'}},
            )

        return {'success': True, 'document': doc_meta}
    except ValueError as err:
        _remove_file(file_path)
        return JSONResponse(status_code=400, content={'error': {'message': str(err)}})
    except Exception as err:
        _remove_file(file_path)
        logger.error('knowledge: ingest error', {'error': str(err)})
        return JSONResponse(status_code=500, content={'error': {'message': str(err) or '文档处理失败'}})


@knowledge_router.get('/documents')
async def list_documents(category: str = None):
    docs = get_doc_registry()
    if category:
        docs = [d for d in docs if d['category'] == category]
    return {'documents': docs}


@knowledge_router.delete('/documents/{doc_id}')
async def remove_document(doc_id: str):
    try:
        await delete_document(doc_id)
        return {'success': True}
    except Exception as err:
        return JSONResponse(status_code=404, content={'error': {'message': str(err)}})


@knowledge_router.post('/query/stream')
async def rag_stream(req: dict):
    """
    RAG 流式问答接口

    第一步：校验问题内容
    第二步：检索知识库相关文档
    第三步：流式生成回答（含来源引用）
    第四步：推送完成事件
    """
    question = (req.get('question') or '').strip()
    category = req.get('category')

    if not question:
        return JSONResponse(status_code=400, content={'error': {'message': '问题不能为空'}})

    async def event_generator():
        try:
            yield sse_event('status', {'message': '正在检索相关文档...'})

            result = await rag_query_stream(question, {'category': category})
            sources = result['sources']

            yield sse_event('sources', {'sources': sources})

            if not sources:
                yield sse_event('token', {'token': '知识库中未找到相关内容，请尝试上传相关文档后再提问。'})
                yield sse_event('done', {})
                return

            yield sse_event('status', {'message': '正在生成回答...'})

            async for token in result['stream_answer']():
                yield sse_event('token', {'token': token})

            yield sse_event('done', {})
            logger.info('knowledge: query done', {'question': question[:40], 'sources': len(sources)})
        except Exception as err:
            logger.error('knowledge: query error', {'error': str(err)})
            yield sse_error(err)

    return EventSourceResponse(event_generator())


@knowledge_router.get('/categories')
async def get_categories():
    docs = get_doc_registry()
    cats = list({d['category'] for d in docs})
    return {
        'categories': [
            {'value': '', 'label': '全部文档'},
            *[{'value': c, 'label': c} for c in cats],
        ]
    }
