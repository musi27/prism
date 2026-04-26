# Prism Data Plane Spec

## 1. Introduction

This document specifies the Prism data plane: the HTTP API between an SDK and the UI server, the JSON log format written to disk, and the serialization rules that govern both. It is the authoritative public contract. The Python SDK in `prism/` is one implementation of it; SDKs in other languages (TypeScript next, then anything else HTTP-capable) build against this document, not against the Python source.

This spec is descriptive of today's behavior. Changes to it are deliberate and visible in git history; treat any divergence between the running code and this document as a bug.

## 2. Core concepts

- **Agent.** A logical instance identified by a developer-chosen `agent_id` (string).
- **Run.** A single execution of an agent, identified by `run_id` (string). Today's format: `run_{YYYYMMDD_HHMMSS}_{6-hex}`. Treat `run_id` as opaque; do not parse it.
- **Tool call.** One invocation of an instrumented tool function. Produces one log entry on disk and, if gated, one approval request over HTTP.
- **Approval.** A blocking handshake the SDK initiates before executing a gated tool. The UI server holds the request open until a reviewer decides or the SDK times out.
- **Heartbeat.** A status ping the SDK sends roughly every 30 seconds while a run is active.
- **Coverage.** A summary entry the SDK writes once per run comparing the agent's full tool list to the tools wrapped with `@prism.watch` (or the equivalent in non-Python SDKs).

## 3. HTTP API

Base URL: `${PRISM_UI_URL}` resolves to `http://${PRISM_UI_HOST}:${PRISM_UI_PORT}` (defaults: `localhost`, `4242`). Both override knobs are documented in the README and apply to the SDK side and the server side identically.

All request and response bodies are JSON unless noted. All endpoints below are over plain HTTP today; TLS is out of scope for the current spec.

### 3.1 SDK → server

#### `POST /api/approvals` — request approval (blocking)

The SDK calls this immediately before executing a tool listed in `require_approval_for`. The server holds the request open until a reviewer decides via `POST /api/approvals/{id}/approve` or `/reject`. The Python SDK sets a 600-second timeout; other SDKs should choose a similar large value and surface timeout to the caller.

Request body:

```json
{
  "id": "a3f8c1b2e4d6",
  "tool_name": "write_summary",
  "skill_context": "reporting",
  "agent_id": "file-watcher-v1",
  "run_id": "run_20260425_103011_a1b2c3",
  "tool_count": 7,
  "tool_purpose": "Write a markdown summary of the input file to disk.",
  "recent_calls": [
    { "tool_name": "watch_folder", "inputs_preview": "{\"path\": \"/tmp/in\"}", "status": "success",  "duration_ms": 12.4,   "timestamp_end": "2026-04-25T10:30:01.000Z" },
    { "tool_name": "read_file",    "inputs_preview": "{\"path\": \"/tmp/in/note.md\"}", "status": "success", "duration_ms": 3.1, "timestamp_end": "2026-04-25T10:30:01.020Z" }
  ],
  "trigger_reason": "This tool is in your require_approval_for list",
  "inputs": {
    "path": "/tmp/out/summary.md",
    "content": "# Summary\n\nLong content here…",
    "overwrite": true,
    "max_bytes": 4096
  }
}
```

Fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Caller-generated approval id; opaque. The Python SDK uses 12 hex chars. |
| `tool_name` | string | yes | Name of the tool being requested. |
| `skill_context` | string \| null | yes (nullable) | Optional skill grouping; `null` if not set. |
| `agent_id` | string | yes | The agent's name. |
| `run_id` | string | yes | The current run id. |
| `tool_count` | number | yes | Tool calls completed in this run so far. |
| `tool_purpose` | string | yes | Tool docstring (or empty string `""` if none). |
| `recent_calls` | array | yes | Up to 5 entries, oldest first. Each: `{tool_name, inputs_preview, status, duration_ms, timestamp_end}`. `status ∈ {"success", "failure", "rejected"}`. `inputs_preview` is a short JSON string ≤ 60 chars (with `…`/`...` truncation). |
| `trigger_reason` | string | yes | Short human-readable phrase explaining why this tool is gated. |
| `inputs` | object | yes | Tool inputs; types preserved per Section 5. |

Response body:

```json
{ "status": "approved" }
```

`status ∈ {"approved", "rejected"}`. The SDK enforces the contract: on `"rejected"` it raises a permission-denied error to the agent loop; on `"approved"` it executes the tool. If the network call fails or times out, SDKs may fall back to a local prompt (the Python SDK does this) or surface the error.

#### `POST /api/runs/heartbeat` — non-blocking status ping

Cadence: every ~30 seconds while a run is active.

Request:

```json
{
  "run_id": "run_20260425_103011_a1b2c3",
  "agent_id": "file-watcher-v1",
  "status": "active",
  "tool_count": 7,
  "missing_tools": []
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `run_id` | string | yes | |
| `agent_id` | string | yes | |
| `status` | string | yes | `"active"` if a tool is currently executing, `"idle"` otherwise. |
| `tool_count` | number | yes | Tool calls completed so far this run. |
| `missing_tools` | array of string | yes | Names of declared tools not wrapped with `@prism.watch` (may be empty). |

Response: `{"status": "ok"}`.

#### `POST /api/runs/warnings` — uninstrumented-tool warnings

Sent at configure time when the SDK detects declared tools that are not instrumented. Optional if the SDK has nothing to report.

Request:

```json
{
  "run_id": "run_20260425_103011_a1b2c3",
  "agent_id": "file-watcher-v1",
  "missing": ["delete_record"]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `run_id` | string | yes | |
| `agent_id` | string | yes | |
| `missing` | array of string | yes | Tool names that are declared but not instrumented. |

Response: `{"status": "ok"}`.

#### `POST /api/runs/complete` — run completion signal

Sent when the agent process exits cleanly (atexit, SIGTERM, SIGINT, or explicit call). Idempotent.

Request:

```json
{ "run_id": "run_20260425_103011_a1b2c3" }
```

Response: `{"status": "ok"}`.

### 3.2 UI → server (consumed by the frontend)

These endpoints serve the local UI. Third-party SDKs do not need to implement them, but they are part of the public spec because non-Python UI frontends (or remote dashboards) may consume them.

#### `GET /api/runs`

Lists all runs across log files, summarized. Response: array of:

```json
{
  "run_id": "run_20260425_103011_a1b2c3",
  "agent_id": "file-watcher-v1",
  "timestamp": "2026-04-25T10:30:11.000Z",
  "tool_call_count": 42,
  "has_errors": false
}
```

#### `GET /api/runs/{run_id}?page&page_size`

Paginated tool-call entries for a single run. `page_size ∈ [1, 500]`, default 100. `page ≥ 1`, default 1.

Response:

```json
{
  "entries": [ /* tool-call entries per Section 4 */ ],
  "total": 137,
  "page": 1,
  "has_more": true
}
```

Coverage entries (per Section 4) are excluded from `entries`.

#### `GET /api/runs/{run_id}/coverage`

Coverage report for a run, or `null` if none was written. Shape: see Section 4 (coverage entry).

#### `GET /api/agents`

Lists agents with aggregated run data and the most recent coverage. Response: array of:

```json
{
  "agent_id": "file-watcher-v1",
  "total_runs": 12,
  "last_run_timestamp": "2026-04-25T10:30:11.000Z",
  "last_run_has_errors": false,
  "coverage_pct": 100,
  "coverage_instrumented": ["watch_folder", "read_file", "write_summary"],
  "coverage_missing": [],
  "runs": [ /* run summaries */ ]
}
```

#### `GET /api/approvals`

Currently-pending approvals. Response: array of approval-request payloads (same shape as `POST /api/approvals` body, including `id`).

#### `GET /api/approvals/history`

Resolved decisions, most recent first. Each entry:

```json
{
  "id": "a3f8c1b2e4d6",
  "tool_name": "write_summary",
  "inputs": { "path": "/tmp/out/summary.md", "overwrite": true },
  "decision": "approved",
  "timestamp": "2026-04-25T10:30:14.123Z"
}
```

`decision ∈ {"approved", "rejected"}`.

#### `POST /api/approvals/{approval_id}/approve`

Resolves a pending approval to `approved`. No request body. Response: `{"status": "approved"}`. Side effect: appends to `logs/_approvals.json` (Section 4.3).

#### `POST /api/approvals/{approval_id}/reject`

Resolves a pending approval to `rejected`. No request body. Response: `{"status": "rejected"}`. Same persistence side effect.

### 3.3 SSE — `GET /api/live`

`text/event-stream` channel for the UI to subscribe to live updates. Four event types:

| Event name | Payload | Sent when |
|---|---|---|
| *(default, no `event:` line)* | The raw JSONL line of one tool-call entry | A new line is appended to a run's log file. |
| `heartbeat` | `{run_id, agent_id, status, tool_count, missing_tools, last_heartbeat}` | A run's heartbeat changes. |
| `run_complete` | `{run_id}` | A run has been signaled complete. |
| `approval_request` | The full approval-request payload (Section 3.1.1) including `id` | A new approval is pending. |

The stream skips entries that pre-existed before the connection was opened; only new entries are emitted. Implementations should expect that and not rely on initial-state replay through SSE — use the `GET` endpoints to load initial state.

## 4. JSON log format

### 4.1 File naming and rotation

- File path: `{log_path}/{run_id}.jsonl`. `log_path` defaults to `./logs` and is configurable via `prism.configure(log_path=...)` or the equivalent in non-Python SDKs.
- Rotated files: `{log_path}/{run_id}_2.jsonl`, `{run_id}_3.jsonl`, …
- Rotation triggers when the current file reaches **10,000 entries** OR **10 MB**, whichever first.
- Format: JSONL — one JSON object per line, newline-terminated, no comments, no blank lines.

### 4.2 Per-line shape

A line is one of two record types. Consumers branch on the presence of `type: "coverage"`.

#### Tool-call entry (the common case)

```json
{
  "agent_id": "file-watcher-v1",
  "run_id": "run_20260425_103011_a1b2c3",
  "timestamp_start": "2026-04-25T10:30:11.000Z",
  "timestamp_end":   "2026-04-25T10:30:11.012Z",
  "duration_ms": 12.4,
  "tool_name": "watch_folder",
  "skill_context": null,
  "inputs":  { "path": "/tmp/in" },
  "outputs": { "result": ["note.md", "todo.md"] },
  "status": "success",
  "error": null
}
```

| Field | Type | Notes |
|---|---|---|
| `agent_id` | string | |
| `run_id` | string | |
| `timestamp_start` | string | ISO 8601 with timezone. |
| `timestamp_end` | string | ISO 8601 with timezone. |
| `duration_ms` | number | Milliseconds, may be fractional. |
| `tool_name` | string | |
| `skill_context` | string \| null | |
| `inputs` | object | Types preserved per Section 5. |
| `outputs` | object | Types preserved per Section 5. |
| `status` | string | `"success"` or `"failure"`. |
| `error` | string \| null | Error message if `status == "failure"`, else `null`. |

#### Coverage entry (one per run)

Written once per run, typically just before the run completes.

```json
{
  "type": "coverage",
  "agent_id": "file-watcher-v1",
  "run_id": "run_20260425_103011_a1b2c3",
  "instrumented": ["watch_folder", "read_file", "write_summary"],
  "missing": [],
  "total": 3,
  "covered": 3,
  "percentage": 100
}
```

| Field | Type | Notes |
|---|---|---|
| `type` | string | Always `"coverage"`. |
| `agent_id` | string | |
| `run_id` | string | |
| `instrumented` | array of string | Tool names that are wrapped. |
| `missing` | array of string | Tool names declared but not wrapped. |
| `total` | number | `len(instrumented) + len(missing)`. |
| `covered` | number | `len(instrumented)`. |
| `percentage` | number | Integer 0-100. |

### 4.3 Resolved approvals (separate file)

`{log_path}/_approvals.json` — a single JSON array (not JSONL) holding resolved approval decisions. Persisted by the UI server, not the SDK. The leading underscore excludes it from run-file scans.

```json
[
  {
    "id": "a3f8c1b2e4d6",
    "tool_name": "write_summary",
    "inputs": { "path": "/tmp/out/summary.md", "overwrite": true },
    "decision": "approved",
    "timestamp": "2026-04-25T10:30:14.123Z"
  }
]
```

## 5. Serialization behavior

JSON-native values (strings, numbers, booleans, lists, objects, `null`) are preserved as typed values. Non-JSON-serializable values (Python `datetime`, `pathlib.Path`, custom classes; equivalents in other languages) are coerced to strings via `str()` before transmission.

Both paths use the same rule:

- **Log entries** — `json.dumps(asdict(entry), default=str)` in `prism/spec.py:write_log_entry`.
- **Approval API payload** — `_serialize_inputs(inputs)` round-trips the dict through `json.dumps(default=str)` (`prism/__init__.py:_serialize_inputs`).

Any value that round-trips in the log path round-trips in the approval-API path. Non-Python SDKs should follow the same rule: prefer the JSON-native type when available, fall back to the language's default string representation otherwise.

Anything Prism reasons about programmatically — tool names, statuses, durations, identifiers — lives in typed top-level fields, not inside `inputs` or `outputs`. SDKs should not place control-plane signals inside the inputs/outputs dicts.

## 6. Versioning and stability

This spec is the durable definition of Prism's data plane. Any HTTP-capable language can implement an SDK against it.

- **Breaking changes** ship across all official SDKs simultaneously and are announced in release notes.
- **Additive changes** (new fields, new endpoints, new event types) ship in the Python SDK first; other official SDKs follow on a defined cadence (the parity rule from `docs/roadmap.md` step 2).
- **Tolerance.** Implementations on both sides should accept unknown fields without erroring. SDKs may emit additional optional fields that the server preserves but does not interpret.
- **Spec evolution.** Treat any divergence between the running code and this document as a bug. Fix in either direction: update the code to match the spec, or update the spec deliberately.

A spec version number is not assigned yet. Versioning policy is a follow-up decision once at least one non-Python SDK is in flight.

## 7. Examples

### 7.1 A complete approval request

```json
{
  "id": "a3f8c1b2e4d6",
  "tool_name": "write_summary",
  "skill_context": "reporting",
  "agent_id": "file-watcher-v1",
  "run_id": "run_20260425_103011_a1b2c3",
  "tool_count": 7,
  "tool_purpose": "Write a markdown summary of the input file to disk. Refuses to overwrite unless overwrite=True.",
  "recent_calls": [
    { "tool_name": "watch_folder", "inputs_preview": "{\"path\": \"/tmp/in\"}",          "status": "success",  "duration_ms":   12.4, "timestamp_end": "2026-04-25T10:30:01.000Z" },
    { "tool_name": "read_file",    "inputs_preview": "{\"path\": \"/tmp/in/note.md\"}", "status": "success",  "duration_ms":    3.1, "timestamp_end": "2026-04-25T10:30:01.020Z" },
    { "tool_name": "summarize",    "inputs_preview": "{\"length\": 500, \"text\": \"…\"}", "status": "failure",  "duration_ms":  812.0, "timestamp_end": "2026-04-25T10:30:01.832Z" },
    { "tool_name": "summarize",    "inputs_preview": "{\"length\": 200, \"text\": \"…\"}", "status": "rejected", "duration_ms":    0.0, "timestamp_end": "2026-04-25T10:30:02.001Z" },
    { "tool_name": "summarize",    "inputs_preview": "{\"length\": 200, \"text\": \"…\"}", "status": "success",  "duration_ms":  743.5, "timestamp_end": "2026-04-25T10:30:02.751Z" }
  ],
  "trigger_reason": "This tool is in your require_approval_for list",
  "inputs": {
    "path": "/tmp/out/summary.md",
    "content": "# Summary\n\nThis is a generated markdown summary of approximately 1500 characters describing the input note. Long content continues here for thousands of characters.",
    "overwrite": true,
    "max_bytes": 4096
  }
}
```

### 7.2 The matching response

```json
{ "status": "approved" }
```

### 7.3 Tool-call log entry (success)

```json
{
  "agent_id": "file-watcher-v1",
  "run_id": "run_20260425_103011_a1b2c3",
  "timestamp_start": "2026-04-25T10:30:02.000Z",
  "timestamp_end":   "2026-04-25T10:30:02.751Z",
  "duration_ms": 743.5,
  "tool_name": "summarize",
  "skill_context": "reporting",
  "inputs": { "length": 200, "text": "…" },
  "outputs": { "result": "Generated summary text…" },
  "status": "success",
  "error": null
}
```

### 7.4 Tool-call log entry (failure)

```json
{
  "agent_id": "file-watcher-v1",
  "run_id": "run_20260425_103011_a1b2c3",
  "timestamp_start": "2026-04-25T10:30:01.020Z",
  "timestamp_end":   "2026-04-25T10:30:01.832Z",
  "duration_ms": 812.0,
  "tool_name": "summarize",
  "skill_context": "reporting",
  "inputs": { "length": 500, "text": "…" },
  "outputs": {},
  "status": "failure",
  "error": "RateLimitError: 429 too many requests"
}
```

### 7.5 Coverage entry

```json
{
  "type": "coverage",
  "agent_id": "file-watcher-v1",
  "run_id": "run_20260425_103011_a1b2c3",
  "instrumented": ["watch_folder", "read_file", "write_summary"],
  "missing": [],
  "total": 3,
  "covered": 3,
  "percentage": 100
}
```

### 7.6 Heartbeat payload

```json
{
  "run_id": "run_20260425_103011_a1b2c3",
  "agent_id": "file-watcher-v1",
  "status": "idle",
  "tool_count": 7,
  "missing_tools": []
}
```

### 7.7 Resolved-decision entry (`_approvals.json`)

```json
{
  "id": "a3f8c1b2e4d6",
  "tool_name": "write_summary",
  "inputs": { "path": "/tmp/out/summary.md", "overwrite": true },
  "decision": "approved",
  "timestamp": "2026-04-25T10:30:14.123Z"
}
```
