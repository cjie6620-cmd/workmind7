#!/usr/bin/env python3
"""T2-08 Knowledge upload/delete + multi-worker consistency under real Embedding.

From repo root (with acceptance override already up):
  python scripts/acceptance_t2_08_knowledge.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(ROOT / "server-py" / ".env"),
    "-f",
    str(ROOT / "docker" / "docker-compose.prod.yml"),
    "-f",
    str(ROOT / "docker" / "docker-compose.acceptance.yml"),
]
BASE = f"http://127.0.0.1:{os.environ.get('APP_PORT', '3001')}"
EVIDENCE = ROOT / "docs" / "acceptance-evidence" / "t2"
LOG: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    LOG.append(msg)


def run(cmd: list[str], check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    log(f"$ {' '.join(cmd)}")
    cp = subprocess.run(
        cmd,
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if cp.stdout:
        log(cp.stdout.strip()[:3000])
    if cp.stderr:
        log(cp.stderr.strip()[:1500])
    if check and cp.returncode != 0:
        raise RuntimeError(f"cmd failed: {cmd}")
    return cp


def http_json(method: str, url: str, body: dict | None = None, token: str | None = None, timeout: float = 120):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return exc.code, payload


def wait_ready(timeout_s: int = 300) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            code, payload = http_json("GET", f"{BASE}/health/ready", timeout=10)
            if code == 200:
                log(f"ready: {payload}")
                return
            log(f"waiting ready={code} {payload}")
        except Exception as exc:
            log(f"waiting ready err={exc}")
        time.sleep(5)
    raise RuntimeError("ready timeout")


def login() -> str:
    code, payload = http_json(
        "POST",
        f"{BASE}/api/auth/login",
        {"username": "admin", "password": "admin123"},
    )
    if code != 200:
        raise RuntimeError(f"login failed: {code} {payload}")
    return payload.get("accessToken") or payload.get("access_token")


def assert_embed_ready() -> None:
    out = run(
        COMPOSE
        + [
            "exec",
            "-T",
            "-e",
            "PYTHONPATH=/app",
            "app",
            "python",
            "-c",
            "from app.services.model import get_embeddings\n"
            "e=get_embeddings()\n"
            "v=e.embed_query('t2-08 probe')\n"
            "print('EMBED_OK', len(v))",
        ],
        timeout=600,
    )
    if "EMBED_OK" not in out.stdout:
        raise RuntimeError(f"embedding not ready: {out.stdout}")


def upload_text(token: str, text: str, filename: str) -> str:
    boundary = f"----wm{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"{text}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/knowledge/documents",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        code = resp.status
    log(f"upload => {code} {payload}")
    if code != 200:
        raise RuntimeError(f"upload failed: {payload}")
    doc_id = (
        payload.get("id")
        or payload.get("docId")
        or (payload.get("document") or {}).get("id")
        or (payload.get("doc") or {}).get("id")
    )
    if not doc_id:
        raise RuntimeError(f"missing doc id: {payload}")
    return str(doc_id)


def list_docs(token: str) -> list:
    code, payload = http_json("GET", f"{BASE}/api/knowledge/documents", token=token)
    if code != 200:
        raise RuntimeError(f"list docs failed: {code} {payload}")
    return payload.get("documents") or payload.get("items") or payload.get("docs") or []


def delete_doc(token: str, doc_id: str) -> None:
    code, payload = http_json("DELETE", f"{BASE}/api/knowledge/documents/{doc_id}", token=token)
    log(f"delete => {code} {payload}")
    if code != 200:
        raise RuntimeError(f"delete failed: {code} {payload}")


def multi_worker_list_consistent(token: str, doc_id: str) -> None:
    """Hit list endpoint concurrently; all responses must include the same doc id."""
    import concurrent.futures

    def once():
        docs = list_docs(token)
        ids = {d.get("id") or d.get("docId") for d in docs}
        return doc_id in ids, len(docs)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: once(), range(16)))
    ok = sum(1 for hit, _ in results if hit)
    if ok != 16:
        raise RuntimeError(f"multi-worker list inconsistent: hits={ok}/16 results={results[:4]}")
    log(f"PASS multi-worker list consistency hits={ok}/16")


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    try:
        # Ensure acceptance stack
        run(COMPOSE + ["up", "-d", "app"], timeout=600)
        wait_ready(360)
        assert_embed_ready()
        token = login()

        marker = f"T2-08 vacation policy {uuid.uuid4().hex[:8]}"
        text = (
            f"{marker}\n"
            "公司年假政策：员工每年享有 10 天带薪年假，可按半天拆分申请。\n"
            "请假需提前 3 个工作日提交，紧急情况可事后补单。\n"
        )
        doc_id = upload_text(token, text, f"t2-08-{uuid.uuid4().hex[:6]}.txt")
        docs = list_docs(token)
        if not any((d.get("id") or d.get("docId")) == doc_id for d in docs):
            raise RuntimeError("uploaded doc missing from list")
        multi_worker_list_consistent(token, doc_id)

        delete_doc(token, doc_id)
        docs_after = list_docs(token)
        if any((d.get("id") or d.get("docId")) == doc_id for d in docs_after):
            raise RuntimeError("doc still listed after delete")

        # Registry / vector orphan probe via in-container registry dump if available
        probe = run(
            COMPOSE
            + [
                "exec",
                "-T",
                "-e",
                "PYTHONPATH=/app",
                "app",
                "python",
                "-c",
                "from app.services.rag.ingest import get_doc_registry\n"
                "import asyncio\n"
                "async def main():\n"
                "  reg=await get_doc_registry()\n"
                f"  print('HAS', '{doc_id}' in (reg or {{}}))\n"
                "asyncio.run(main())",
            ],
            check=False,
        )
        log(probe.stdout.strip())

        path = EVIDENCE / f"t2-08-knowledge-{time.strftime('%Y%m%d-%H%M%S')}.md"
        path.write_text(
            "\n".join(
                [
                    "# T2-08 Knowledge Acceptance",
                    "",
                    f"- Date: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                    "- Embedding: local mounted `/models/bge-m3`",
                    f"- Uploaded doc: `{doc_id}`",
                    "- Multi-worker list consistency: 16/16",
                    "- Delete removed doc from list",
                    "",
                    "## Log",
                    "",
                    "```",
                    *LOG,
                    "```",
                    "",
                    "PASS",
                ]
            ),
            encoding="utf-8",
        )
        log(f"PASS T2-08 -> {path}")
        print(f"T2_08_OK evidence={path}")
        return 0
    except Exception as exc:
        path = EVIDENCE / f"t2-08-knowledge-{time.strftime('%Y%m%d-%H%M%S')}.md"
        path.write_text("\n".join(["# T2-08 FAIL", "", str(exc), "", "```", *LOG, "```"]), encoding="utf-8")
        log(f"FATAL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
