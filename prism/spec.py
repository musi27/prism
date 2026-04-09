import glob as globmod
import json
import os
import re
from dataclasses import dataclass, asdict

MAX_ENTRIES = 10_000
MAX_BYTES = 10 * 1024 * 1024  # 10MB


@dataclass
class ToolCallEntry:
    agent_id: str
    run_id: str
    timestamp_start: str  # ISO 8601
    timestamp_end: str    # ISO 8601
    duration_ms: float
    tool_name: str
    skill_context: str | None
    inputs: dict
    outputs: dict
    status: str  # "success" or "failure"
    error: str | None


def _get_run_files(run_id: str, log_dir: str) -> list[str]:
    """Return all log files for a run, sorted by rotation number."""
    base = os.path.join(log_dir, f"{run_id}.jsonl")
    pattern = os.path.join(log_dir, f"{run_id}_*.jsonl")
    files = []
    if os.path.exists(base):
        files.append(base)
    for f in sorted(globmod.glob(pattern)):
        files.append(f)
    return files


def _current_log_path(run_id: str, log_dir: str) -> str:
    """Return the current (latest) log file path, rotating if needed."""
    files = _get_run_files(run_id, log_dir)
    if not files:
        return os.path.join(log_dir, f"{run_id}.jsonl")

    latest = files[-1]

    # Check if rotation is needed
    needs_rotate = False
    try:
        size = os.path.getsize(latest)
        if size >= MAX_BYTES:
            needs_rotate = True
        else:
            with open(latest) as f:
                line_count = sum(1 for line in f if line.strip())
            if line_count >= MAX_ENTRIES:
                needs_rotate = True
    except OSError:
        pass

    if not needs_rotate:
        return latest

    # Determine next rotation number
    match = re.search(r'_(\d+)\.jsonl$', latest)
    next_num = (int(match.group(1)) + 1) if match else 2
    return os.path.join(log_dir, f"{run_id}_{next_num}.jsonl")


def write_log_entry(entry: ToolCallEntry, log_dir: str = "./logs") -> None:
    """Append a tool call log entry as a JSON line, rotating if needed."""
    os.makedirs(log_dir, exist_ok=True)
    path = _current_log_path(entry.run_id, log_dir)
    with open(path, "a") as f:
        f.write(json.dumps(asdict(entry), default=str) + "\n")
