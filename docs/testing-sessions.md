# Smoke testing sessions

A **testing session** groups one investigation. A **browser worker** is a running Chromium process. Each loaded plan creates a separate **attempt**; retries keep earlier findings and evidence.

## Start an investigation

```bash
reverie sessions create 'Demo QA — login and navigation' --id demo-smoke \
  --environment qa --revision <source-commit>
reverie --session admin start --url http://localhost:8080 --testing-session demo-smoke --follow-along
reverie --session admin spec .reverie/specs/admin.md
reverie --session admin pilot
reverie ui
```

`create` selects the new session for subsequently started workers. `sessions attach ID` selects an existing session; it does not move running workers. Use a new testing session for a new investigation or testing day. `sessions archive ID` keeps earlier work accessible without making it the next worker's default.

Start additional workers with the same testing-session ID. Spec front matter `role: admin` or `role: support` groups attempts by workflow and role. The dashboard separates current work, failures or blocks, results, and expired evidence. Earlier attempts remain reviewable through **Load earlier attempts**; the initial snapshot is bounded. Selecting an activity frame pins that evidence until **Back to live**.

## Watch and supervise

The dashboard uses an authenticated WebSocket for snapshots, ordered changes, reconnection, and current frames. Slow viewers get the latest frame or a fresh snapshot. Connection health, frame age, application waiting, and narration holds are shown separately. The standalone `/watch` compatibility page still polls; the main dashboard does not.

The dashboard server currently collects worker watch state over local authenticated HTTP. This bridge is independent of the browser WebSocket and does not reread historical trails on live ticks. Historical evidence is loaded when selected.

- **Fast:** execution proceeds without waiting for speech.
- **Follow along:** the next operation waits for actual audio playback to finish plus **350 ms**. Page and model preparation overlap speech; elapsed preparation counts toward the padding.
- **One operation at a time:** resume for one pilot operation, then pause again.

There is at most one pending speech beat after the current utterance. Skip cancels that beat; an audio error requires retry or skip. Selecting a narration source in the dashboard mutes other live workers in the same testing session. Muting speech preserves captions and the trail.

```bash
reverie --session admin audio --mode follow --padding-ms 350
reverie --session admin audio --skip
reverie --session admin control pause
reverie --session admin control take
# Authorized manual commands use --actor human after takeover.
reverie --session admin --actor human act e7
reverie --session admin control release
reverie --session admin control resume
```

Pause is requested immediately; an action already executing finishes at its safe boundary. Takeover changes the ownership epoch and invalidates old commands. A model response produced before takeover or changed instructions cannot execute afterward. Release clears pending proposals and observes again. Human/coordinator requests can be claimed and resolved in the dashboard or through `request claim` / `request resolve`.

## Visual evidence and honest verdicts

The pilot sees the raw screen and an annotated targeting image at meaningful decisions. `inspect` supplies native-size crops and loading diagnostics. DOM references identify and guard a target; the pilot must judge whether the rendered control is perceivable and usable. Delegated intents prepare guarded proposals; the pilot approves the target against the next screenshot before acting. Offscreen targets are revealed first, then chosen again visually.

Rapidly changing geometry or animation can prevent a consistent screenshot and create a coordinator checkpoint. The pilot does not automatically retry screenshot freshness. After restoring visual evidence, run `observe`, inspect `checkpoints`, resolve the affected checkpoint with a factual note, and start `pilot` again. The resumed attempt keeps the earlier evidence and recovery history.

At each step review boundary, Reverie refreshes screenshot pixels and verifies their observation binding. An unchanged valid image can be reused as evidence for the current step. Failed captures or a changed page block visual verification until a fresh observation succeeds.

A functional check alone cannot establish a pass. Missing screenshots or unavailable visual review block verification. Serious visual findings make the step fail even when a workaround succeeds; cosmetic findings retain their severity. Unsupported or ambiguous custom widgets require a checkpoint rather than an invented target.

```bash
reverie --session admin inspect e7 --json
reverie --session admin state --json
reverie --session admin changes --after 120 --timeout 20 --json
```

The JSON state includes logical session, run, worker, incarnation, observation, control epoch, an atomic state revision, and a separate durable event cursor. Durable changes survive reconnects and process restarts. `events --follow --json` emits newline-delimited JSON batches. `progress --json` is a compact current summary. Reuse an `--operation-id` only with the same command, arguments, worker, owner, epoch, and incarnation. When a worker control value is omitted, the reservation binds it to the current value. An uncertain running operation is never replayed automatically. After control or worker identity changes, inspect state and events before deciding what to do next.

## Screenshot privacy

Masking is **best effort, not a guarantee**. Unsupported fields and masking faults can leave content visible. Do not use real secrets without your own review. Recognized populated fields receive local stripes; empty fields keep placeholders and borders. Invalid selectors and masking faults warn while keeping fresh captures where possible. No whole-frame fallback, numeric-substring matching or stale-target fan-out is used. Existing evidence is not rewritten. Masking is on by default. Set `REVERIE_MASK_SECRETS=0` before session startup to turn it off for frames, clips and UI review. Turning it off writes any visible secrets into frames and clips; text/trail redaction and native password bullets remain unchanged. See [screenshot privacy](screenshot-privacy.md) for configuration and limits.

UI review uses verified capture-produced images. Invalid final evidence requires fresh capture or a declined review. Capture provenance does not guarantee that all sensitive content is hidden.

## Temporary evidence

Purpose (`smoke`, `regression`, `exploratory`), result, diagnosis, and lifetime are independent fields. New sessions are temporary unless created with `--retained`.

| Evidence | Cleanup eligibility |
|---|---|
| Successful temporary attempt | 24 hours after completion |
| Failed, blocked, incomplete, or untriaged finding | Held for triage |
| Triaged temporary failure | Seven days after triage |
| Active, pinned, retained, or shared with protected evidence | Preserved |

```bash
reverie runs pin <run-id>
reverie runs triage <run-id> --triage confirmed --json
reverie runs expire             # preview
reverie runs expire --apply     # remove due screenshots/trails; preserve result metadata
reverie runs list --include-expired --json
```

Cleanup is explicit; it is not a background timer. Expiry preserves a durable result tombstone. Evidence outside the project's own run directory is protected. Multiple attempts sharing one directory are cleaned only when every attempt is eligible.

## Synthetic smoke lab

Run the [local smoke lab server](../examples/smoke-lab/server.py) to exercise delayed, obscured, and missing visual controls. See the [lab instructions](../examples/smoke-lab/README.md) and example specs for the workflow.

## Agent integrations

See [agent integrations](agent-integrations.md) for MCP tools, portable plugins, and optional Claude Channels. The local stdio adapter does not advertise OpenAI MCP Events.
