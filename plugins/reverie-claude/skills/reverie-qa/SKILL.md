---
name: reverie-qa
description: Coordinate a Reverie logical QA session and its browser workers. Use for browser smoke tests, reconnecting to a running test, handling QA requests, or triaging retained evidence.
---

# Reverie QA coordination

Create one logical session for the user's testing objective and reuse its ID across workers. Read `session_snapshot` before acting, then continue from `session_events` with the returned cursor.

Give every `worker_call` and `worker_inspect` a stable, unique `operation_id`. Reuse the same ID only when retrying the exact same operation. If a worker reports an operation as running, treat its outcome as uncertain and inspect current state before deciding what to do next.

Use `worker_inspect` when pixel evidence is needed. It returns an MCP image rather than embedding image data in text. Resolve live requests through their worker when possible so the browser process can reconcile its prompt or checkpoint.

Preview retention before purging. Pin evidence that must survive cleanup, and triage failed, blocked, or incomplete runs before their retention clock begins.
