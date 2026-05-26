# ERP 路由：智能填单 + 审批流
import asyncio
import json
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from ..services.erp.parser import parse_expense_form, parse_leave_form, check_compliance
from ..services.erp.approval import run_approval_flow, APPROVAL_ROLES
from ..utils.errors import send_sse_error
from ..utils.logger import logger

erp_router = APIRouter()

applications = {}


def sse(event, data):
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


@erp_router.post('/parse')
async def erp_parse(req: dict):
    text = (req.get('text') or '').strip()
    form_type = req.get('formType')

    if not text:
        return JSONResponse(status_code=400, content={'error': {'message': '描述不能为空'}})
    if form_type not in ('expense', 'leave'):
        return JSONResponse(status_code=400, content={'error': {'message': 'formType 必须是 expense 或 leave'}})

    try:
        if form_type == 'expense':
            form = await parse_expense_form(text)
            alerts = check_compliance(form)
            form.warnings = list(form.warnings) + alerts
        else:
            form = await parse_leave_form(text)

        # pydantic model → dict
        form_dict = form.model_dump(by_alias=False)
        return {'success': True, 'form': form_dict, 'formType': form_type}
    except Exception as err:
        logger.error('erp: parse error', {'error': str(err)})
        return JSONResponse(status_code=500, content={'error': {'message': '解析失败，请检查输入内容'}})


@erp_router.post('/submit/stream')
async def erp_submit_stream(req: dict):
    form_data = req.get('formData')
    form_type = req.get('formType')
    applicant_name = req.get('applicantName', '申请人')

    if not form_data or not form_type:
        return JSONResponse(status_code=400, content={'error': {'message': '缺少表单数据'}})

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
        await queue.put(sse(event_type, data))
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
            await queue.put(send_sse_error(err))
        finally:
            done_event.set()

    asyncio.create_task(run())

    async def event_generator():
        yield sse('start', {'appId': app_id, 'formType': form_type})
        while not done_event.is_set() or not queue.empty():
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.5)
                yield item
            except asyncio.TimeoutError:
                continue
        yield sse('done', {'appId': app_id})

    return StreamingResponse(
        event_generator(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@erp_router.get('/applications')
async def list_applications():
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
    app = applications.get(app_id)
    if not app:
        return JSONResponse(status_code=404, content={'error': {'message': '申请不存在'}})
    return app


@erp_router.get('/roles')
async def erp_roles():
    return {'roles': list(APPROVAL_ROLES.values())}
