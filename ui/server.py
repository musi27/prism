import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

app = FastAPI(title="Prism")

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")

# In-memory pending approvals: id -> {"detail": dict, "event": asyncio.Event, "result": str|None}
_pending: dict[str, dict] = {}
# Resolved approval decisions, persisted to disk
APPROVALS_FILE = os.path.join(LOG_DIR, "_approvals.json")


def _load_resolved() -> list[dict]:
    if os.path.exists(APPROVALS_FILE):
        with open(APPROVALS_FILE) as f:
            return json.load(f)
    return []


def _save_resolved(resolved: list[dict]) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(APPROVALS_FILE, "w") as f:
        json.dump(resolved, f, indent=2)


_resolved: list[dict] = _load_resolved()

# Run status from heartbeats: run_id -> {agent_id, status, tool_count, last_heartbeat, missing_tools}
_run_status: dict[str, dict] = {}

# Runs that the SDK has signaled as complete
_completed_runs: set[str] = set()

# Warnings: run_id -> [missing tool names]
_run_warnings: dict[str, list[str]] = {}


def _read_log_file(path: str) -> list[dict]:
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _get_run_files(run_id: str) -> list[str]:
    """Return all log files for a run, sorted by rotation number."""
    log_path = Path(LOG_DIR)
    if not log_path.exists():
        return []
    base = log_path / f"{run_id}.jsonl"
    files = []
    if base.exists():
        files.append((0, str(base)))
    for f in log_path.glob(f"{run_id}_*.jsonl"):
        match = re.search(r'_(\d+)\.jsonl$', f.name)
        if match:
            files.append((int(match.group(1)), str(f)))
    files.sort(key=lambda x: x[0])
    return [f for _, f in files]


def _read_all_run_entries(run_id: str) -> list[dict]:
    """Read all entries across rotated files for a run."""
    entries = []
    for f in _get_run_files(run_id):
        entries.extend(_read_log_file(f))
    return entries


def _read_run_entries_paginated(run_id: str, page: int, page_size: int) -> tuple[list[dict], int, bool]:
    """Read entries for a run with pagination. Returns (entries, total, has_more)."""
    all_files = _get_run_files(run_id)
    if not all_files:
        return [], 0, False

    # Count total entries and collect all non-coverage entries
    all_entries = []
    for f in all_files:
        for entry in _read_log_file(f):
            if entry.get("type") != "coverage":
                all_entries.append(entry)

    total = len(all_entries)
    start = (page - 1) * page_size
    end = start + page_size
    page_entries = all_entries[start:end]
    has_more = end < total
    return page_entries, total, has_more


# --- HTML ---

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path) as f:
        return f.read()


# --- API ---

@app.get("/api/runs")
async def list_runs():
    """List all runs with summary info."""
    log_path = Path(LOG_DIR)
    if not log_path.exists():
        return []
    # Collect unique run_ids from base files
    seen_runs = set()
    runs = []
    for f in sorted(log_path.glob("*.jsonl"), reverse=True):
        if f.name.startswith("_"):
            continue
        # Extract run_id from filename (strip rotation suffix)
        name = f.stem
        match = re.match(r'^(.+?)(?:_\d+)?$', name)
        run_id = match.group(1) if match else name
        if run_id in seen_runs:
            continue
        seen_runs.add(run_id)

        entries = _read_all_run_entries(run_id)
        tool_entries = [e for e in entries if e.get("type") != "coverage"]
        if not tool_entries:
            continue
        runs.append({
            "run_id": run_id,
            "agent_id": tool_entries[0].get("agent_id", "unknown"),
            "timestamp": tool_entries[0].get("timestamp_start", ""),
            "tool_call_count": len(tool_entries),
            "has_errors": any(e.get("status") == "failure" for e in tool_entries),
        })
    return runs


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500)):
    """Get log entries for a run, paginated."""
    entries, total, has_more = _read_run_entries_paginated(run_id, page, page_size)
    return {"entries": entries, "total": total, "page": page, "has_more": has_more}


@app.get("/api/runs/{run_id}/coverage")
async def get_run_coverage(run_id: str):
    """Get coverage report for a specific run, if one was written."""
    for entry in _read_all_run_entries(run_id):
        if entry.get("type") == "coverage":
            return entry
    return None


@app.get("/api/agents")
async def list_agents():
    """List unique agents with aggregated run data."""
    log_path = Path(LOG_DIR)
    if not log_path.exists():
        return []
    agents: dict[str, dict] = {}
    seen_runs = set()
    for f in sorted(log_path.glob("*.jsonl"), reverse=True):
        if f.name.startswith("_"):
            continue
        name = f.stem
        match = re.match(r'^(.+?)(?:_\d+)?$', name)
        run_id = match.group(1) if match else name
        if run_id in seen_runs:
            continue
        seen_runs.add(run_id)

        entries = _read_all_run_entries(run_id)
        tool_entries = [e for e in entries if e.get("type") != "coverage"]
        if not tool_entries:
            continue
        agent_id = tool_entries[0].get("agent_id", "unknown")
        run_info = {
            "run_id": run_id,
            "timestamp": tool_entries[0].get("timestamp_start", ""),
            "tool_call_count": len(tool_entries),
            "has_errors": any(e.get("status") == "failure" for e in tool_entries),
        }
        if agent_id not in agents:
            # First run seen is the most recent (files sorted reverse)
            cov_entry = next((e for e in entries if e.get("type") == "coverage"), None)
            agents[agent_id] = {
                "agent_id": agent_id,
                "total_runs": 0,
                "last_run_timestamp": run_info["timestamp"],
                "last_run_has_errors": run_info["has_errors"],
                "coverage_pct": cov_entry.get("percentage") if cov_entry else None,
                "coverage_instrumented": cov_entry.get("instrumented", []) if cov_entry else [],
                "coverage_missing": cov_entry.get("missing", []) if cov_entry else [],
                "runs": [],
            }
        agents[agent_id]["total_runs"] += 1
        agents[agent_id]["runs"].append(run_info)
    return list(agents.values())


# --- Heartbeat & Run completion ---

@app.post("/api/runs/warnings")
async def run_warnings(request: Request):
    """SDK sends uninstrumented tool warnings at configure time."""
    body = await request.json()
    run_id = body.get("run_id", "")
    missing = body.get("missing", [])
    if run_id and missing:
        _run_warnings[run_id] = missing
    return {"status": "ok"}


@app.post("/api/runs/heartbeat")
async def heartbeat(request: Request):
    """SDK sends heartbeats every 30s to report run status."""
    body = await request.json()
    run_id = body.get("run_id", "")
    if run_id:
        missing = body.get("missing_tools", [])
        if missing:
            _run_warnings[run_id] = missing
        _run_status[run_id] = {
            "agent_id": body.get("agent_id", "unknown"),
            "status": body.get("status", "idle"),
            "tool_count": body.get("tool_count", 0),
            "missing_tools": _run_warnings.get(run_id, []),
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        }
    return {"status": "ok"}


@app.post("/api/runs/complete")
async def mark_run_complete(request: Request):
    """SDK calls this to signal a run has finished."""
    body = await request.json()
    run_id = body.get("run_id", "")
    if run_id:
        _completed_runs.add(run_id)
        if run_id in _run_status:
            _run_status[run_id]["status"] = "complete"
    return {"status": "ok"}


# --- SSE Live Feed ---

@app.get("/api/live")
async def live_feed(request: Request):
    async def generate():
        seen: dict[str, int] = {}  # filename -> lines already sent
        active_runs: set[str] = set()
        last_heartbeats: dict[str, str] = {}
        first_scan = True  # skip old entries on initial connect

        while True:
            if await request.is_disconnected():
                break
            log_path = Path(LOG_DIR)
            if log_path.exists():
                for f in sorted(log_path.glob("*.jsonl")):
                    if f.name.startswith("_"):
                        continue
                    try:
                        lines = f.read_text().strip().split("\n") if f.stat().st_size > 0 else []
                    except OSError:
                        continue
                    prev = seen.get(f.name, 0)
                    if len(lines) > prev:
                        if not first_scan:
                            # Only stream new entries written after SSE connected
                            for line in lines[prev:]:
                                line = line.strip()
                                if not line:
                                    continue
                                entry = json.loads(line)
                                run_id = entry.get("run_id", "")
                                # A new log entry means the agent is running right now
                                active_runs.add(run_id)
                                if entry.get("type") != "coverage":
                                    yield {"data": line}
                        seen[f.name] = len(lines)

            first_scan = False

            # Only stream heartbeats for runs not yet completed
            for rid, info in _run_status.items():
                if info.get("status") == "complete" or rid in _completed_runs:
                    continue
                if info.get("status") in ("active", "idle"):
                    active_runs.add(rid)
                hb = info.get("last_heartbeat", "")
                if hb != last_heartbeats.get(rid):
                    last_heartbeats[rid] = hb
                    yield {"event": "heartbeat", "data": json.dumps({"run_id": rid, **info})}

            # Check for runs the SDK has signaled as complete
            for rid in list(active_runs):
                if rid in _completed_runs or _run_status.get(rid, {}).get("status") == "complete":
                    yield {"event": "run_complete", "data": json.dumps({"run_id": rid})}
                    active_runs.discard(rid)

            # Stream pending approvals
            for aid, info in list(_pending.items()):
                if not info.get("streamed"):
                    yield {"event": "approval_request", "data": json.dumps({"id": aid, **info["detail"]})}
                    info["streamed"] = True
            await asyncio.sleep(1)

    return EventSourceResponse(generate())


# --- Approvals ---

@app.get("/api/approvals")
async def list_approvals():
    """List all pending approvals."""
    return [{"id": aid, **info["detail"]} for aid, info in _pending.items() if info["result"] is None]


@app.get("/api/approvals/history")
async def approval_history():
    """List all resolved approval decisions."""
    return list(reversed(_resolved))


@app.post("/api/approvals")
async def create_approval(request: Request):
    """SDK calls this to request approval. Blocks until human decides."""
    body = await request.json()
    approval_id = body.get("id", os.urandom(8).hex())
    event = asyncio.Event()
    _pending[approval_id] = {
        "detail": body,
        "event": event,
        "result": None,
        "streamed": False,
    }
    await event.wait()
    result = _pending[approval_id]["result"]
    del _pending[approval_id]
    return {"status": result}


@app.post("/api/approvals/{approval_id}/approve")
async def approve(approval_id: str):
    if approval_id not in _pending:
        return {"error": "Not found"}
    detail = _pending[approval_id]["detail"]
    _resolved.append({
        "id": approval_id,
        "tool_name": detail.get("tool_name", "unknown"),
        "inputs": detail.get("inputs", {}),
        "decision": "approved",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_resolved(_resolved)
    _pending[approval_id]["result"] = "approved"
    _pending[approval_id]["event"].set()
    return {"status": "approved"}


@app.post("/api/approvals/{approval_id}/reject")
async def reject(approval_id: str):
    if approval_id not in _pending:
        return {"error": "Not found"}
    detail = _pending[approval_id]["detail"]
    _resolved.append({
        "id": approval_id,
        "tool_name": detail.get("tool_name", "unknown"),
        "inputs": detail.get("inputs", {}),
        "decision": "rejected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_resolved(_resolved)
    _pending[approval_id]["result"] = "rejected"
    _pending[approval_id]["event"].set()
    return {"status": "rejected"}


def main(host: str, port: int) -> None:
    print(f"Prism UI running at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
