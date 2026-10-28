# Agent integrations

Reverie exposes its local coordination store and running browser workers through a dependency-free MCP server:

```bash
python -m reverie.control.mcp --root /path/to/project
```

The process uses MCP over stdio. Standard output is reserved for JSON-RPC messages; diagnostics from the existing Reverie CLI remain on standard error. The adapter does not start browser workers. Start those with `reverie start` and use the same project root.

## Tools and safety boundaries

The server provides logical session creation, listing, atomic snapshots, cursor-based compact events, coordination request handling, run pinning and triage, retention previews or confirmed cleanup, and browser worker calls.

`worker_call` accepts only an explicit command allowlist with per-command argument validation. It delegates every browser operation through the existing authenticated loopback RPC. Commands that accept secrets, arbitrary file output, shell checkpoints, daemon reload or stop, long blocking questions, raw history, or raw screenshots are not exposed. Each worker operation needs a stable `operation_id`; server-side command deduplication prevents an uncertain in-flight operation from being automatically executed again.

`worker_inspect` is the visual-evidence path. It returns the raw screen and an optional target crop as MCP image content and removes its base64 bytes from JSON and text results. Other tool results strip image fields and bound strings, lists, event pages, and total text output.

`session_snapshot` returns a bounded page of recent attempts; use `runs_next` as `run_offset` to load older attempts, and `run_total` to see the complete count. Oversized event results preserve cursors and summarize evidence without losing event identity.

A snapshot contains an atomic `revision` for session state and a separate `cursor` for the latest durable event. Use that cursor, or the one returned by `session_events`, as the next `after` value. The cursor uses the per-session event sequence, not the global event ID. Filtering by event type still advances the cursor across events that were filtered out.

Resolving a request with `worker_id` routes the resolution through the live browser worker, allowing it to reconcile an open prompt or checkpoint. A direct durable resolution is available when the worker is offline; the worker must reconcile that state when it reconnects.

Retention cleanup is a two-step operation. `retention_expire` previews by default. Actual evidence removal requires both `dry_run: false` and `confirm_purge: true`; the store still applies active, pinned, untriaged, containment, symlink, and shared-attempt protections.

## Codex

The portable local bundle is in `plugins/reverie-codex`. Its `mcp.json` launches the same Python module from the project working directory, and its skill explains the cursor and operation-ID workflow. The Reverie checkout must be the active Python project, so no package installation step is needed.

Codex supports local stdio MCP servers configured with a command and arguments. You can also configure the adapter directly in a trusted project's `.codex/config.toml`:

```toml
[mcp_servers.reverie]
command = "python"
args = ["-m", "reverie.control.mcp", "--root", "."]
cwd = "."
```

Restart the MCP client after changing configuration. See the [official Codex MCP documentation](https://developers.openai.com/codex/mcp).

The local stdio adapter does not advertise MCP Events. Use cursor polling through `session_events` to receive changes. See the [official MCP Events documentation](https://developers.openai.com/plugins/build/mcp-events).

## Claude Code

The bundle in `plugins/reverie-claude` uses the same `python -m reverie.control.mcp` executable and enables the adapter's optional `--claude-channel` mode. Standard MCP tools work without channel delivery.

Claude Code Channels are a research preview. The adapter advertises `experimental["claude/channel"]` only when the flag is present and emits `notifications/claude/channel` only for compact actionable events such as requests, checkpoints, findings, failures, blocks, and human-input needs. Routine frames and progress events are not pushed.

Custom channels must be explicitly enabled by the host. During the research preview, test the local plugin interactively with the development-channel flag and follow any organization policy or confirmation prompt:

```bash
claude --plugin-dir ./plugins/reverie-claude \
  --dangerously-load-development-channels plugin:reverie-qa@local
```

The exact plugin identifier depends on the marketplace or local loading method. Confirm it with Claude Code's plugin and MCP status views. Noninteractive sessions ignore the development-channel bypass, organization policy can block channels, and Claude Code can silently drop channel notifications when the server was not opted in. The durable event cursor remains the source of truth. See Anthropic's [Channels reference](https://code.claude.com/docs/en/channels-reference).

## Bare stdio configuration

Any MCP host that supports local stdio servers can launch:

```json
{
  "command": "python",
  "args": ["-m", "reverie.control.mcp", "--root", "/absolute/project/path"]
}
```

The adapter implements `initialize`, `notifications/initialized`, `ping`, `tools/list`, and `tools/call`. Tool results include both `structuredContent` and a serialized text block for compatibility. Malformed protocol messages use JSON-RPC errors; tool input, business, and worker execution failures use MCP tool results with `isError: true` so the model can correct its call.
