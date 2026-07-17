#!/usr/bin/env python3
"""T2 in-container probes: multi-worker Redis lock + budget atomic reserve.

Run inside the app container:
  python /tmp/acceptance_t2_incontainer.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


async def t2_01_workflow_lock() -> None:
    from app.services.workflow.state_store import (
        acquire_workflow_lock,
        release_workflow_lock,
        save_workflow_run,
        get_workflow_run,
        delete_workflow_run,
    )

    thread_id = f"t2_lock_{uuid.uuid4().hex}"
    await save_workflow_run(
        thread_id,
        {
            "workflowId": "weekly_report",
            "userId": "admin-t2",
            "status": "paused",
            "values": {},
            "intermediates": [],
        },
    )
    try:
        tokens = await asyncio.gather(*[acquire_workflow_lock(thread_id) for _ in range(12)])
        winners = [t for t in tokens if t]
        if len(winners) != 1:
            _fail(f"T2-01 expected exactly 1 lock winner, got {len(winners)}")
        await release_workflow_lock(thread_id, winners[0])
        run = await get_workflow_run(thread_id)
        if not run or run.get("status") != "paused":
            _fail("T2-01 run snapshot missing or status mutated unexpectedly")
        print("PASS T2-01 workflow Redis lock arbitration (1/12 winners)")
    finally:
        await delete_workflow_run(thread_id)


async def t2_02_budget_reserve() -> None:
    from app.config import config
    from app.services import budget_guard as bg

    # Force enforce for this probe regardless of process env used at import time.
    os.environ["BUDGET_ENFORCE"] = "true"
    config["budget"]["enforce"] = True
    await bg.save_budget(1.0)

    day = date.today()
    # Clear ledger keys for a clean counter.
    from app.core.redis_client import get_redis

    ledger_key, reservations_key = bg._ledger_keys(day)
    r = get_redis()
    await asyncio.to_thread(r.delete, ledger_key, reservations_key)

    async def one() -> str:
        try:
            reservation = await bg._reserve_amount(
                reserved_cny=0.6,
                estimated_input_tokens=100,
                reserved_output_tokens=200,
                model_name="deepseek-chat",
                target_day=day,
            )
            return "ok" if reservation.reservation_id else "degraded"
        except Exception as exc:
            name = type(exc).__name__
            detail = getattr(exc, "detail", None)
            if isinstance(detail, dict) and "日预算" in str(detail.get("message", "")):
                return "rejected"
            if "预算" in str(exc) or name == "HTTPException":
                return "rejected"
            return f"error:{exc}"

    results = await asyncio.gather(*[one() for _ in range(16)])
    ok = sum(1 for x in results if x == "ok")
    rejected = sum(1 for x in results if x == "rejected")
    other = [x for x in results if x not in {"ok", "rejected", "degraded"}]
    if other:
        _fail(f"T2-02 unexpected reserve outcomes: {other[:3]}")
    # budget=1.0, each reserve=0.6 → at most 1 success under enforce
    if ok > 1:
        _fail(f"T2-02 budget pierced: ok={ok} rejected={rejected} results={results}")
    if ok < 1:
        _fail(f"T2-02 expected at least 1 reserve success, got ok={ok} rejected={rejected}")
    print(f"PASS T2-02 budget atomic reserve (ok={ok}, rejected={rejected})")


async def main() -> None:
    await t2_01_workflow_lock()
    await t2_02_budget_reserve()
    print("INCONTAINER_OK")


if __name__ == "__main__":
    asyncio.run(main())
