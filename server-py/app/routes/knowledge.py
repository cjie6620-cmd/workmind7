# 知识库路由：文档管理 + RAG 问答
import json
import os
import shutil
import time

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse

from ..services.rag.ingest import ingest_document, get_doc_registry, delete_document
from ..services.rag.query import rag_query_stream
from ..utils.errors import send_sse_error
from ..utils.logger import logger

knowledge_router = APIRouter()

UPLOAD_DIR = './uploads'
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTS = {'.txt', '.md', '.pdf'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def sse(event, data):
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


@knowledge_router.post('/documents')
async def upload_document(
    file: UploadFile = File(None),
    title: str = Form(None),
    category: str = Form('通用'),
    content: str = Form(None),
):
    try:
        if file:
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in ALLOWED_EXTS:
                return JSONResponse(
                    status_code=400,
                    content={'error': {'message': f'不支持的文件格式 {ext}，只支持 {", ".join(ALLOWED_EXTS)}'}},
                )

            # 保存到磁盘
            safe_name = f'{int(time.time() * 1000)}_{file.filename}'
            file_path = os.path.join(UPLOAD_DIR, safe_name)
            with open(file_path, 'wb') as f:
                shutil.copyfileobj(file.file, f)

            doc_meta = await ingest_document(
                file_path=file_path,
                file_name=file.filename,
                title=title or os.path.splitext(file.filename)[0],
                category=category or '通用',
            )
        elif content:
            tmp_path = os.path.join(UPLOAD_DIR, f'tmp_{int(time.time() * 1000)}.txt')
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(content)

            doc_meta = await ingest_document(
                file_path=tmp_path,
                file_name=(title or '文本内容') + '.txt',
                title=title or '未命名文档',
                category=category or '通用',
            )
        else:
            return JSONResponse(
                status_code=400,
                content={'error': {'message': '请上传文件或提供文本内容'}},
            )

        return {'success': True, 'document': doc_meta}
    except Exception as err:
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
    question = (req.get('question') or '').strip()
    category = req.get('category')

    if not question:
        return JSONResponse(status_code=400, content={'error': {'message': '问题不能为空'}})

    async def event_generator():
        try:
            yield sse('status', {'message': '正在检索相关文档...'})

            result = await rag_query_stream(question, {'category': category})
            sources = result['sources']

            yield sse('sources', {'sources': sources})

            if not sources:
                yield sse('token', {'token': '知识库中未找到相关内容，请尝试上传相关文档后再提问。'})
                yield sse('done', {})
                return

            yield sse('status', {'message': '正在生成回答...'})

            async for token in result['stream_answer']():
                yield sse('token', {'token': token})

            yield sse('done', {})
            logger.info('knowledge: query done', {'question': question[:40], 'sources': len(sources)})
        except Exception as err:
            logger.error('knowledge: query error', {'error': str(err)})
            yield send_sse_error(err)

    return StreamingResponse(
        event_generator(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


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
