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

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from ..auth.dependencies import get_current_user
from ..auth.models import UserContext
from ..services.rag.ingest import (
    ingest_document,
    get_doc_registry,
    delete_document,
    filter_docs_for_user,
)
from ..services.rag.query import rag_query_stream
from ..services.chat.memory import save_message, get_session_info
from ..schemas.requests import KnowledgeQueryRequest
from ..utils.sse import sse_event, sse_error
from ..utils.file_validate import validate_file, validate_ext, MAX_FILE_SIZE
from ..utils.logger import logger
from ..utils.session_guard import assert_session_owner

knowledge_router = APIRouter()

# 文件上传目录
UPLOAD_DIR = "./uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _serialize_sources(sources: list[dict]) -> list[dict]:
    """将检索层内部字段转换为稳定的公开引用契约。"""
    serialized = []
    for source in sources:
        raw_score = None
        for field in ("score", "rerank_score", "vector_score"):
            if source.get(field) is not None:
                raw_score = source[field]
                break
        try:
            score = float(raw_score) if raw_score is not None else 0.0
        except (TypeError, ValueError):
            score = 0.0

        serialized.append(
            {
                "content": source.get("content", ""),
                "title": source.get("title", "未知来源"),
                "docId": source.get("docId"),
                "category": source.get("category"),
                "score": round(score, 4),
            }
        )
    return serialized


def _safe_file_name(filename):
    name = (filename or "").replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r"[^\w.\-一-鿿]+", "_", name)
    return name or f"upload_{int(time.time() * 1000)}.txt"


def _remove_file(path):
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _parse_multipart_boundary(content_type):
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            return part[len("boundary=") :]
    return None


async def _read_multipart(request):
    """
    手动解析 multipart/form-data，避免 python-multipart 与 torch 的段错误冲突。
    仅提取第一个文件字段和普通字段。
    """
    content_type = request.headers.get("content-type", "")
    boundary = _parse_multipart_boundary(content_type)
    if not boundary:
        return {}, None

    # 第一步：按 Content-Length 提前拒绝超限请求，避免整包读入内存
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_FILE_SIZE + 64 * 1024:
                raise ValueError(f"上传体积超过限制（最大 {MAX_FILE_SIZE // (1024 * 1024)}MB）")
        except ValueError as err:
            if "上传体积" in str(err):
                raise
            raise ValueError("非法 Content-Length") from err

    body = await request.body()
    if len(body) > MAX_FILE_SIZE + 64 * 1024:
        raise ValueError(f"上传体积超过限制（最大 {MAX_FILE_SIZE // (1024 * 1024)}MB）")
    delimiter = b"--" + boundary.encode()

    fields = {}
    file_data = None

    parts = body.split(delimiter)
    for part in parts:
        if not part or part.strip() in (b"", b"--"):
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_section, content = part.split(b"\r\n\r\n", 1)
        content = content.rstrip(b"\r\n")
        if content.endswith(b"--"):
            content = content[:-2]

        header_str = header_section.decode("utf-8", errors="replace")
        name_match = re.search(r'name="([^"]*)"', header_str)
        filename_match = re.search(r'filename="([^"]*)"', header_str)

        if not name_match:
            continue
        name = name_match.group(1)

        if filename_match:
            file_data = {
                "filename": filename_match.group(1),
                "content": content,
            }
        else:
            fields[name] = content.decode("utf-8", errors="replace")

    return fields, file_data


@knowledge_router.post("/documents")
async def upload_document(
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """
    上传文档接口

    第一步：解析请求体（multipart 文件 或 JSON 文本）
    第二步：校验文件大小、扩展名、内容安全性
    第三步：写入临时文件，调用 ingest 向量化入库
    第四步：清理临时文件，返回文档元信息
    """
    file_path = None
    try:
        content_type = request.headers.get("content-type", "")

        if "multipart/form-data" in content_type:
            try:
                fields, file_data = await _read_multipart(request)
            except ValueError as err:
                return JSONResponse(status_code=400, content={"error": {"message": str(err)}})
            title = fields.get("title") or "未命名文档"
            category = fields.get("category") or "通用"

            if not file_data:
                return JSONResponse(
                    status_code=400,
                    content={"error": {"message": "请上传文件或提供文本内容"}},
                )

            original_name = _safe_file_name(file_data["filename"])
            file_content = file_data["content"]

            if len(file_content) > MAX_FILE_SIZE:
                return JSONResponse(
                    status_code=400,
                    content={"error": {"message": "文件不能超过 10MB"}},
                )

            try:
                validate_ext(original_name)
            except ValueError as err:
                return JSONResponse(status_code=400, content={"error": {"message": str(err)}})

            safe_name = f"{uuid.uuid4().hex}_{original_name}"
            file_path = os.path.join(UPLOAD_DIR, safe_name)
            with open(file_path, "wb") as f:
                f.write(file_content)

            try:
                validate_file(file_path, original_name)
            except ValueError as err:
                _remove_file(file_path)
                return JSONResponse(status_code=400, content={"error": {"message": str(err)}})

            doc_meta = await ingest_document(
                file_path=file_path,
                file_name=original_name,
                title=title or os.path.splitext(original_name)[0],
                category=category,
                owner_user_id=user.user_id,
            )

        elif "application/json" in content_type:
            try:
                payload = await request.json()
            except json.JSONDecodeError:
                return JSONResponse(status_code=400, content={"error": {"message": "JSON 格式不正确"}})

            title = payload.get("title", "未命名文档")
            category = payload.get("category", "通用")
            content = payload.get("content")

            if not content:
                return JSONResponse(
                    status_code=400,
                    content={"error": {"message": "请上传文件或提供文本内容"}},
                )

            if len(content.encode("utf-8")) > MAX_FILE_SIZE:
                return JSONResponse(
                    status_code=400,
                    content={"error": {"message": "文本内容不能超过 10MB"}},
                )

            file_path = os.path.join(UPLOAD_DIR, f"tmp_{uuid.uuid4().hex}.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            doc_meta = await ingest_document(
                file_path=file_path,
                file_name=(title or "文本内容") + ".txt",
                title=title,
                category=category,
                owner_user_id=user.user_id,
            )
        else:
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "不支持的 Content-Type"}},
            )

        return {"success": True, "document": doc_meta}
    except ValueError as err:
        _remove_file(file_path)
        return JSONResponse(status_code=400, content={"error": {"message": str(err)}})
    except Exception as err:
        _remove_file(file_path)
        logger.error("knowledge: ingest error", {"error": str(err)})
        return JSONResponse(status_code=500, content={"error": {"message": str(err) or "文档处理失败"}})


@knowledge_router.get("/documents")
async def list_documents(
    category: str | None = None,
    user: UserContext = Depends(get_current_user),
):
    docs = filter_docs_for_user(
        await get_doc_registry(),
        user_id=user.user_id,
        is_admin=user.role == "admin",
    )
    if category:
        docs = [d for d in docs if d["category"] == category]
    return {"documents": docs}


@knowledge_router.delete("/documents/{doc_id}")
async def remove_document(
    doc_id: str,
    user: UserContext = Depends(get_current_user),
):
    try:
        await delete_document(
            doc_id,
            requester_user_id=user.user_id,
            is_admin=user.role == "admin",
        )
        return {"success": True}
    except PermissionError as err:
        return JSONResponse(status_code=403, content={"error": {"message": str(err)}})
    except ValueError as err:
        return JSONResponse(status_code=404, content={"error": {"message": str(err)}})
    except Exception as err:
        logger.error("knowledge: delete error", {"error": str(err), "docId": doc_id})
        return JSONResponse(status_code=500, content={"error": {"message": "文档删除失败"}})


@knowledge_router.post("/query/stream")
async def rag_stream(
    req: KnowledgeQueryRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """
    RAG 流式问答接口

    第一步：校验问题内容
    第二步：检索知识库相关文档
    第三步：流式生成回答（含来源引用）
    第四步：推送完成事件
    第五步：持久化问答记录到 conversations 表
    """
    question = req.question.strip()
    category = req.category
    user_id = user.user_id
    session_id = req.sessionId or f"knowledge_{user_id}_{uuid.uuid4().hex[:12]}"

    if not question:
        return JSONResponse(status_code=400, content={"error": {"message": "问题不能为空"}})

    await assert_session_owner(session_id, user_id)

    async def event_generator():
        full_answer = ""
        sources = []
        try:
            await save_message(session_id, "user", question, user_id=user_id)

            yield sse_event("status", {"message": "正在检索相关文档..."})

            result = await rag_query_stream(
                question,
                {
                    "category": category,
                    "owner_user_id": user_id,
                    "is_admin": user.role == "admin",
                },
            )
            sources = _serialize_sources(result["sources"])

            yield sse_event("sources", {"sources": sources})

            if not sources:
                full_answer = "知识库中未找到相关内容，请尝试上传相关文档后再提问。"
                yield sse_event("token", {"token": full_answer})
                await save_message(
                    session_id,
                    "assistant",
                    full_answer,
                    metadata={"sources": []},
                    user_id=user_id,
                )
                yield sse_event("done", {"sessionId": session_id})
                return

            yield sse_event("status", {"message": "正在生成回答..."})

            disconnected = False
            async for token in result["stream_answer"]():
                if await request.is_disconnected():
                    disconnected = True
                    break
                full_answer += token
                yield sse_event("token", {"token": token})

            # 断连时仍持久化已生成片段，与 Chat 契约一致
            if full_answer:
                await save_message(
                    session_id,
                    "assistant",
                    full_answer,
                    metadata={"sources": sources, "incomplete": disconnected},
                    user_id=user_id,
                )
            if not disconnected:
                yield sse_event("done", {"sessionId": session_id})
                logger.info("knowledge: query done", {"question": question[:40], "sources": len(sources)})
        except Exception as err:
            logger.error("knowledge: query error", {"error": str(err)})
            if full_answer:
                await save_message(
                    session_id,
                    "assistant",
                    full_answer,
                    metadata={"sources": sources, "incomplete": True},
                    user_id=user_id,
                )
            yield sse_error(err)

    return EventSourceResponse(event_generator())


@knowledge_router.get("/categories")
async def get_categories(user: UserContext = Depends(get_current_user)):
    docs = filter_docs_for_user(
        await get_doc_registry(),
        user_id=user.user_id,
        is_admin=user.role == "admin",
    )
    cats = list({d["category"] for d in docs})
    return {
        "categories": [
            {"value": "", "label": "全部文档"},
            *[{"value": c, "label": c} for c in cats],
        ]
    }


@knowledge_router.get("/history/{session_id}")
async def get_knowledge_history(session_id: str, user: UserContext = Depends(get_current_user)):
    """获取知识库问答历史"""
    await assert_session_owner(session_id, user.user_id)
    info = await get_session_info(session_id)
    return info


@knowledge_router.get("/sessions")
async def get_knowledge_sessions(user: UserContext = Depends(get_current_user)):
    """获取当前用户的知识库会话列表"""
    from sqlalchemy import select, func
    from ..core.database import async_session_factory
    from ..models.entities import Conversation

    async with async_session_factory() as session:
        result = await session.execute(
            select(
                Conversation.session_id,
                func.count(Conversation.id).label("msg_count"),
                func.min(Conversation.created_at).label("created_at"),
            )
            .where(Conversation.session_id.like("knowledge_%"))
            .where(Conversation.user_id == user.user_id)
            .group_by(Conversation.session_id)
            .order_by(func.min(Conversation.created_at).desc())
        )
        rows = result.all()

        sessions = []
        for row in rows:
            sid = row[0]
            # 取第一条用户消息作为标题
            title_stmt = (
                select(Conversation.content)
                .where(Conversation.session_id == sid)
                .where(Conversation.role == "user")
                .order_by(Conversation.created_at)
                .limit(1)
            )
            title_stmt = title_stmt.where(Conversation.user_id == user.user_id)
            r = await session.execute(title_stmt)
            first_msg = r.scalar_one_or_none()
            title = first_msg[:30] + ("..." if first_msg and len(first_msg) > 30 else "") if first_msg else "知识库问答"
            sessions.append(
                {
                    "id": sid,
                    "title": title,
                    "messageCount": row[1],
                    "createdAt": row[2].isoformat() if row[2] else None,
                }
            )

    return {"sessions": sessions}
