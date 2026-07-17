"""工作流输入契约和持久恢复元数据回归测试。"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.routes import workflow as workflow_routes
from app.auth.models import UserContext
from app.routes.workflow import (
    _active_templates,
    _get_intermediates,
    _normalize_input,
    _public_run,
    cancel_run,
)
from app.services.workflow import state_store


def test_meeting_minutes_accepts_legacy_camel_case_and_normalizes_keys():
    result = _normalize_input(
        "meeting_minutes",
        {
            "rawNotes": "张三确认下周上线",
            "meetingTitle": "产品周会",
        },
    )

    assert result == {
        "raw_notes": "张三确认下周上线",
        "meeting_title": "产品周会",
    }


def test_workflow_rejects_empty_or_non_text_input():
    with pytest.raises(ValueError, match="不能为空"):
        _normalize_input("weekly_report", {"points": "   "})
    with pytest.raises(ValueError, match="必须是文本"):
        _normalize_input("email_polish", {"draft": "hello", "recipient": 123})


def test_intermediates_only_expose_present_business_outputs():
    result = _get_intermediates(
        {"highlights": "完成发布", "risks": "", "private": "hidden"},
        "weekly_report",
    )
    assert result == [{"key": "highlights", "label": "提炼的亮点", "value": "完成发布"}]


@pytest.mark.asyncio
async def test_workflow_templates_distinguish_unconfigured_from_all_disabled(monkeypatch):
    monkeypatch.setattr(workflow_routes, "list_wf_configs", AsyncMock(return_value=[]))
    assert await _active_templates() is None

    monkeypatch.setattr(
        workflow_routes,
        "list_wf_configs",
        AsyncMock(
            return_value=[
                {
                    "name": "weekly_report",
                    "isActive": False,
                    "configJson": {},
                }
            ]
        ),
    )
    assert await _active_templates() == []
    assert await workflow_routes.get_templates() == {"templates": []}


def test_completed_workflow_status_exposes_durable_result():
    public = _public_run(
        {
            "threadId": "wf-1",
            "workflowId": "weekly_report",
            "status": "completed",
            "result": "最终周报",
            "updatedAt": "now",
        }
    )
    assert public["status"] == "completed"
    assert public["result"] == "最终周报"


@pytest.mark.asyncio
async def test_explicit_workflow_cancel_writes_tombstone_and_stops_local_task(monkeypatch):
    run = {
        "threadId": "wf-1",
        "workflowId": "weekly_report",
        "userId": "user-a",
        "status": "running",
    }
    save = AsyncMock(return_value={**run, "status": "cancelled"})
    monkeypatch.setattr(workflow_routes, "get_workflow_run", AsyncMock(return_value=run))
    monkeypatch.setattr(workflow_routes, "acquire_workflow_lock", AsyncMock(return_value="lock"))
    monkeypatch.setattr(workflow_routes, "save_workflow_run", save)
    monkeypatch.setattr(workflow_routes, "release_workflow_lock", AsyncMock())

    task = asyncio.create_task(asyncio.sleep(60))
    workflow_routes._workflow_tasks["wf-1"] = task
    response = await cancel_run(
        "wf-1",
        UserContext(user_id="user-a", username="user", role="user"),
    )

    assert response == {"success": True}
    assert task.cancelled()
    assert save.await_args.args[1]["status"] == "cancelled"
    workflow_routes._workflow_tasks.pop("wf-1", None)


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.locks = {}

    def setex(self, key, _ttl, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key) or self.locks.get(key)

    def delete(self, key):
        existed = key in self.values or key in self.locks
        self.values.pop(key, None)
        self.locks.pop(key, None)
        return int(existed)

    def set(self, key, value, *, nx, ex):
        assert nx is True and ex > 0
        if key in self.locks:
            return False
        self.locks[key] = value
        return True

    def eval(self, _script, _keys_count, key, token):
        if self.locks.get(key) == token:
            del self.locks[key]
            return 1
        return 0


@pytest.mark.asyncio
async def test_workflow_snapshot_round_trip_and_resume_lock(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(state_store, "get_redis", lambda: redis)

    saved = await state_store.save_workflow_run(
        "wf_test",
        {
            "workflowId": "weekly_report",
            "userId": "user-a",
            "status": "paused",
            "values": {"points": "done"},
            "intermediates": [],
        },
    )
    loaded = await state_store.get_workflow_run("wf_test")

    assert json.loads(redis.values["workflow:run:wf_test"])["userId"] == "user-a"
    assert loaded == saved

    first = await state_store.acquire_workflow_lock("wf_test")
    second = await state_store.acquire_workflow_lock("wf_test")
    assert first and second is None
    await state_store.release_workflow_lock("wf_test", first)
    assert await state_store.acquire_workflow_lock("wf_test")
