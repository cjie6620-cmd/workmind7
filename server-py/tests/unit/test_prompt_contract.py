"""Prompt 模板类型隔离、版本号和评分边界测试。"""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.services.prompt import prompt_service


@pytest.mark.asyncio
async def test_prompt_update_cannot_overwrite_another_config_type(monkeypatch):
    monkeypatch.setattr(
        prompt_service,
        "db_get",
        AsyncMock(
            return_value={
                "id": "agent-config",
                "configType": "agent",
                "configJson": {},
            }
        ),
    )

    with pytest.raises(ValueError, match="模板不存在"):
        await prompt_service.save_template(
            "name",
            "prompt",
            existing_id="agent-config",
        )


@pytest.mark.asyncio
async def test_prompt_history_version_remains_monotonic_after_trimming(monkeypatch):
    histories = [{"version": number, "systemPrompt": f"v{number}", "savedAt": "now"} for number in range(3, 13)]
    existing = {
        "id": "prompt-id",
        "name": "prompt",
        "configType": "prompt",
        "configJson": {"systemPrompt": "current", "versions": histories},
        "version": 13,
    }
    update = AsyncMock(
        return_value={
            **existing,
            "version": 14,
            "createdAt": "created",
            "updatedAt": "updated",
            "configJson": {},
        }
    )
    monkeypatch.setattr(prompt_service, "db_get", AsyncMock(return_value=existing))
    monkeypatch.setattr(prompt_service, "db_update", update)
    monkeypatch.setattr(
        prompt_service,
        "business_now",
        lambda: datetime.fromisoformat("2026-07-16T00:30:00+08:00"),
    )

    await prompt_service.save_template("prompt", "next", existing_id="prompt-id")

    written = update.await_args.kwargs["config_json"]
    assert len(written["versions"]) == 10
    assert written["versions"][-1]["version"] == 13
    assert written["versions"][-1]["savedAt"] == "2026-07-16T00:30:00+08:00"


def test_prompt_scores_must_be_between_one_and_five():
    with pytest.raises(ValidationError):
        prompt_service.ScoreResult(
            relevance=6,
            accuracy=5,
            clarity=5,
            conciseness=5,
            overall=5,
            winner="A",
            reason="invalid",
        )
