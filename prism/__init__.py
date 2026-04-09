import atexit
import functools
import inspect
import json
import signal
import threading
import urllib.request
import uuid
from datetime import datetime, timezone

from prism.spec import ToolCallEntry, write_log_entry

PRISM_UI_URL = "http://localhost:4242"

# Global configuration
_config = {
    "agent_id": "default-agent",
    "run_id": None,
    "log_path": "./logs",
    "require_approval_for": [],
}

# Registry of tools wrapped with @prism.watch
_watched_tools: set[str] = set()

# Runtime state
_heartbeat_timer: threading.Timer | None = None
_active_tool: str | None = None
_tool_call_count: int = 0


def _post_json(path: str, data: dict, timeout: int = 5) -> dict | None:
    """POST JSON to the UI server. Returns parsed response or None on failure."""
    try:
        payload = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{PRISM_UI_URL}{path}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


# --- Heartbeat ---

def _heartbeat_loop() -> None:
    """Send a heartbeat to the UI server every 30 seconds."""
    global _heartbeat_timer
    _post_json("/api/runs/heartbeat", {
        "run_id": _config["run_id"] or "no_run",
        "agent_id": _config["agent_id"],
        "status": "active" if _active_tool else "idle",
        "tool_count": _tool_call_count,
        "missing_tools": _config.get("missing_tools", []),
    })
    _heartbeat_timer = threading.Timer(30.0, _heartbeat_loop)
    _heartbeat_timer.daemon = True
    _heartbeat_timer.start()


def _stop_heartbeat() -> None:
    global _heartbeat_timer
    if _heartbeat_timer is not None:
        _heartbeat_timer.cancel()
        _heartbeat_timer = None


# --- Shutdown ---

def _shutdown_handler(sig, frame) -> None:
    complete()
    signal.signal(sig, signal.SIG_DFL)
    signal.raise_signal(sig)


def _shutdown_atexit() -> None:
    complete()


# --- Public API ---

def configure(
    agent_id: str = "default-agent",
    log_path: str = "./logs",
    require_approval_for: list[str] | None = None,
    tools: list[str] | None = None,
) -> None:
    """Configure the Prism SDK. Call once per agent before running.

    Args:
        tools: Full list of tool names for coverage reporting. For LangChain
               agents this is auto-detected; for raw API agents, pass explicitly.
    """
    global _complete_called, _tool_call_count
    _config["agent_id"] = agent_id
    _config["log_path"] = log_path
    _config["require_approval_for"] = require_approval_for or []
    _config["run_id"] = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    _complete_called = False
    _tool_call_count = 0

    # Resolve full tool list for coverage
    if tools is not None:
        _config["tools"] = tools
    else:
        # Try LangChain auto-detection
        _config["tools"] = _detect_langchain_tools()

    # Check for uninstrumented tools and warn
    _config["missing_tools"] = []
    resolved = _config.get("tools")
    if resolved:
        missing = [t for t in resolved if t not in _watched_tools]
        _config["missing_tools"] = missing
        for t in missing:
            print(f"  [Prism] Warning: tool '{t}' is not instrumented — add @prism.watch")

    # Start heartbeat
    _stop_heartbeat()
    _heartbeat_loop()

    # Send warnings to UI server
    if _config["missing_tools"]:
        _post_json("/api/runs/warnings", {
            "run_id": _config["run_id"],
            "agent_id": agent_id,
            "missing": _config["missing_tools"],
        })

    # Register shutdown hooks
    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)
    atexit.register(_shutdown_atexit)


def _detect_langchain_tools() -> list[str] | None:
    """Try to detect tool names from the LangChain tool registry."""
    try:
        from langchain_core.tools import BaseTool
        import gc
        tools = []
        for obj in gc.get_objects():
            if isinstance(obj, BaseTool) and hasattr(obj, "name"):
                tools.append(obj.name)
        return tools if tools else None
    except ImportError:
        return None


def watch(fn=None, *, skill: str | None = None):
    """Decorator that instruments a tool function.

    Usage:
        @prism.watch
        def search_web(query): ...

        @prism.watch(skill="prospect_research")
        def write_to_sheet(company, data): ...
    """
    def decorator(func):
        _watched_tools.add(func.__name__)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            global _active_tool, _tool_call_count
            tool_name = func.__name__

            # Build inputs dict from args/kwargs
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            inputs = dict(bound.arguments)

            # Check approval via UI server
            if tool_name in _config["require_approval_for"]:
                print(f"  [Prism] Waiting for approval: {tool_name} — check {PRISM_UI_URL}")
                approval_id = uuid.uuid4().hex[:12]
                result = _post_json("/api/approvals", {
                    "id": approval_id,
                    "tool_name": tool_name,
                    "skill_context": skill,
                    "agent_id": _config["agent_id"],
                    "inputs": {k: str(v) for k, v in inputs.items()},
                }, timeout=600)
                if result is not None:
                    approved = result.get("status") == "approved"
                else:
                    print(f"  [Prism] UI server not running. Falling back to terminal.")
                    print(f"  Tool: {tool_name}")
                    print(f"  Inputs: {inputs}")
                    approved = input("  Approve? (y/n): ").strip().lower() == "y"

                if not approved:
                    entry = ToolCallEntry(
                        agent_id=_config["agent_id"],
                        run_id=_config["run_id"] or "no_run",
                        timestamp_start=datetime.now(timezone.utc).isoformat(),
                        timestamp_end=datetime.now(timezone.utc).isoformat(),
                        duration_ms=0,
                        tool_name=tool_name,
                        skill_context=skill,
                        inputs=inputs,
                        outputs={},
                        status="failure",
                        error="Rejected by human reviewer",
                    )
                    write_log_entry(entry, _config["log_path"])
                    raise PermissionError(f"Tool '{tool_name}' was rejected by reviewer.")

            # Execute and log
            _active_tool = tool_name
            start = datetime.now(timezone.utc)
            try:
                result = func(*args, **kwargs)
                end = datetime.now(timezone.utc)
                duration_ms = (end - start).total_seconds() * 1000

                entry = ToolCallEntry(
                    agent_id=_config["agent_id"],
                    run_id=_config["run_id"] or "no_run",
                    timestamp_start=start.isoformat(),
                    timestamp_end=end.isoformat(),
                    duration_ms=duration_ms,
                    tool_name=tool_name,
                    skill_context=skill,
                    inputs=inputs,
                    outputs={"result": result} if not isinstance(result, dict) else result,
                    status="success",
                    error=None,
                )
                write_log_entry(entry, _config["log_path"])
                _tool_call_count += 1
                return result

            except PermissionError:
                raise
            except Exception as e:
                end = datetime.now(timezone.utc)
                duration_ms = (end - start).total_seconds() * 1000

                entry = ToolCallEntry(
                    agent_id=_config["agent_id"],
                    run_id=_config["run_id"] or "no_run",
                    timestamp_start=start.isoformat(),
                    timestamp_end=end.isoformat(),
                    duration_ms=duration_ms,
                    tool_name=tool_name,
                    skill_context=skill,
                    inputs=inputs,
                    outputs={},
                    status="failure",
                    error=str(e),
                )
                write_log_entry(entry, _config["log_path"])
                _tool_call_count += 1
                raise
            finally:
                _active_tool = None

        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator


def coverage(all_tools: list[str] | None = None) -> dict:
    """Print a coverage report and write it to the run log.

    Typically called automatically by prism.complete(). Can also be called
    manually. If all_tools is not passed, uses the tools list from configure().
    """
    import os

    watched = sorted(_watched_tools)
    resolved = all_tools or _config.get("tools")
    all_t = sorted(set(resolved)) if resolved else watched
    instrumented = [t for t in all_t if t in _watched_tools]
    missing = [t for t in all_t if t not in _watched_tools]

    total = len(all_t)
    count = len(instrumented)
    pct = int(count / total * 100) if total > 0 else 0

    agent_id = _config["agent_id"]
    print(f"\nPrism Coverage Report — {agent_id}")
    print("-" * 48)
    print(f"Instrumented:   {count} / {total} tools ({pct}%)\n")
    for t in instrumented:
        print(f"  [\u2713] {t}")
    for t in missing:
        print(f"  [\u2717] {t}   \u2190 not instrumented")
    if not missing:
        print("\nNo gaps detected.")
    print()

    report = {
        "type": "coverage",
        "agent_id": agent_id,
        "run_id": _config["run_id"] or "no_run",
        "instrumented": instrumented,
        "missing": missing,
        "total": total,
        "covered": count,
        "percentage": pct,
    }

    log_dir = _config["log_path"]
    run_id = _config["run_id"] or "no_run"
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"{run_id}.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(report) + "\n")

    return report


_complete_called: bool = False


def complete() -> None:
    """Signal to the UI server that the current run has finished.

    Idempotent — safe to call multiple times. Automatically runs the
    coverage report before signaling completion.
    """
    global _complete_called
    if _complete_called:
        return
    _complete_called = True
    _stop_heartbeat()
    coverage()
    _post_json("/api/runs/complete", {
        "run_id": _config["run_id"] or "no_run",
    })
