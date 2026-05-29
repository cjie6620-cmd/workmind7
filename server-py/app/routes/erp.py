"""
ERP 路由模块

提供智能填单和审批流功能：
- POST /parse: 自然语言描述解析为结构化表单（报销/请假）
- POST /submit/stream: 提交申请，启动 Multi-Agent 审批流
- GET /applications: 获取申请列表
- GET /applications/{app_id}: 获取申请详情
- GET /roles: 获取审批角色列表

审批流角色：
- applicant: 申请人
- manager: 直属主管
- finance: 财务专员
- hr: HR 专员
- director: 部门总监
"""

import asyncio
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from ..services.erp.parser import parse_expense_form, parse_leave_form
from ..services.erp.approval import run_approval_flow, APPROVAL_ROLES
from ..utils.sse import sse_event, sse_error
from ..utils.logger import logger
from pydantic import ValidationError

erp_router = APIRouter()

# 内存存储申请数据（生产环境应使用数据库）
applications = {}


@erp_router.post('/parse')
async def erp_parse(req: dict):
    """
    表单解析接口

    校验输入 → 调用解析器提取结构化字段 → 返回表单数据
    """
    text = (req.get('text') or '').strip()
    form_type = req.get('formType')

    if not text:
        return JSONResponse(status_code=400, content={'error': {'message': '描述不能为空'}})
    if form_type not in ('expense', 'leave'):
        return JSONResponse(status_code=400, content={'error': {'message': 'formType 必须是 expense 或 leave'}})

    try:
        if form_type == 'expense':
            form = await parse_expense_form(text)
        else:
            form = await parse_leave_form(text)

        form_dict = form.model_dump(by_alias=True, exclude={'warnings'})
        return {'success': True, 'form': form_dict, 'formType': form_type}
    except ValueError as err:
        logger.error('erp: json parse error', {'error': str(err)})
        return JSONResponse(status_code=422, content={'error': {'message': '无法识别表单内容，请调整描述后重试'}})
    except ValidationError as err:
        logger.error('erp: validation error', {'error': str(err)})
        return JSONResponse(status_code=422, content={'error': {'message': '表单格式异常，请调整描述后重试'}})
    except Exception as err:
        logger.error('erp: parse error', {'error': str(err)})
        return JSONResponse(status_code=500, content={'error': {'message': '解析失败，请检查输入内容'}})


@erp_router.post('/submit/stream')
async def erp_submit_stream(req: dict):
    """
    提交申请接口

    第一步：生成申请 ID，存储申请数据
    第二步：创建异步队列，启动后台审批流
    第三步：SSE 流式推送审批过程

    SSE 事件：
    - start: 申请开始
    - plan: 审批流程规划
    - approver_start: 审批人开始审核
    - message: 审批人消息（问题/回答/决定）
    - approver_done: 审批人完成
    - final: 最终结果
    - done: 完成
    """
    form_data = req.get('formData')
    form_type = req.get('formType')
    applicant_name = req.get('applicantName', '申请人')

    if not form_data or not form_type:
        return JSONResponse(status_code=400, content={'error': {'message': '缺少表单数据'}})

    # 生成唯一申请 ID
    app_id = f'APP{int(datetime.now().timestamp() * 1000)}'
    application = {
        'id': app_id,
        'formType': form_type,
        'formData': {**form_data, 'applicantName': applicant_name},
        'status': 'pending',
        'messages': [],
        'createdAt': datetime.now().isoformat(),
    }
    applications[app_id] = application

    queue = asyncio.Queue()
    done_event = asyncio.Event()

    async def collect_event(event_type, data):
        """收集审批流事件"""
        await queue.put(sse_event(event_type, data))
        # 同步存储消息记录
        if event_type == 'message':
            application['messages'].append(data)

    async def run():
        try:
            result = await run_approval_flow(application['formData'], form_type, collect_event)
            application['status'] = result['status']
            application['result'] = result
            application['updatedAt'] = datetime.now().isoformat()
        except Exception as err:
            logger.error('erp: approval error', {'error': str(err), 'appId': app_id})
            await queue.put(sse_error(err))
        finally:
            done_event.set()

    asyncio.create_task(run())

    async def event_generator():
        yield sse_event('start', {'appId': app_id, 'formType': form_type})
        while not done_event.is_set() or not queue.empty():
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.5)
                yield item
            except asyncio.TimeoutError:
                continue
        yield sse_event('done', {'appId': app_id})

    return EventSourceResponse(event_generator())


@erp_router.get('/applications')
async def list_applications():
    """
    获取申请列表

    返回所有申请摘要，按创建时间倒序排列
    """
    app_list = sorted(applications.values(), key=lambda a: a['createdAt'], reverse=True)
    return {
        'applications': [{
            'id': a['id'],
            'formType': a['formType'],
            'status': a['status'],
            'amount': a['formData'].get('totalAmount') or a['formData'].get('total_amount'),
            'reason': a['formData'].get('reason'),
            'days': a['formData'].get('workdays'),
            'createdAt': a['createdAt'],
        } for a in app_list]
    }


@erp_router.get('/applications/{app_id}')
async def get_application(app_id: str):
    """获取申请详情（包含完整表单数据、审批消息记录）"""
    app = applications.get(app_id)
    if not app:
        return JSONResponse(status_code=404, content={'error': {'message': '申请不存在'}})
    return app


@erp_router.get('/roles')
async def erp_roles():
    """获取审批角色定义"""
    return {'roles': list(APPROVAL_ROLES.values())}