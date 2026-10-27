# Changelog

All notable changes to reverie are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) section names, and the
project uses [Semantic Versioning](https://semver.org/). From 0.1.0 on,
[release-please](https://github.com/googleapis/release-please) writes new entries
from the Conventional Commit titles of merged pull requests. Do not edit released
entries by hand.

## 0.2.0 (2026-10-27)

### Features

* Add experimental `--engine liquid` decisions through OpenRouter, using `liquid/d1-ultra` by default. Jev 1.13 remains the default engine.
* Add fresh screenshot and observed-target geometry input for Liquid, with optional image input for Jev.
* Group browser workers, workflows, roles, and attempts into durable testing sessions.
* Stream authenticated dashboard updates with reconnect snapshots and bounded live frames.
* Add follow-along narration with a 350 ms playback boundary, one-operation supervision, requests, and human takeover.
* Add explicit pinning, triage, and temporary evidence cleanup with durable result metadata.
* Add a restricted Codex app-server pilot using an existing local sign-in.
* Add guarded pilot hover and screenshot-coordinate hover, plus CLI `visual-hover`.
* Keep all controls reachable through action buckets, and add guarded screenshot-coordinate actions for unlisted controls.
* Expose coordination through CLI state/events, MCP tools, and portable agent plugins.
* Mask sensitive fields and trusted private regions at the shared screenshot boundary; add `REVERIE_SECRET_SELECTORS`.

### Fixes and verification

* Preserve empty-field placeholders and safe borders, identify privacy masks with opaque stripes, and acquire PNG pixels before masking to avoid JPEG bleed.
* Reuse valid unchanged screenshots for each step while refreshing pixels at review boundaries and rejecting stale evidence.
* Protect hover hits and associated label controls, including disabled, hidden, and inert ancestors.
* Reject missing or stale visual observations before a hosted visual decision.
* Preserve decision-layer history and stated-value guards across the experimental engine.
* Add focused adapter, screenshot freshness, and accepted-action history regression coverage.
* Bind command retries to the worker and effective control identity, including omitted epochs.
* Capture event watermarks atomically with snapshots to avoid skipping updates during resynchronization.
* Discover owned native Wayland or authenticated X11 displays for headed launches, without a silent headless fallback.
* Preserve complete visual signatures across bounded IPC messages and consistent screenshot coordinates.

### Documentation

* Add the narrated demo, recorded from the public build, with captions, a poster, and music credits.
* Document Liquid settings, screenshot data sharing, evaluation limits, and its smaller context budget.

## 0.1.0 (2026-09-28)

First release of reverie as its own repository. It contains only the agent
operation mode of laya-agent.

### Features

* Spec-driven browser test agent: a per-session daemon, a multimodal pilot, local Laya clicks, checkpoints, findings, and narration.
* `reverie` CLI (alias `laya-agent`) with `start`, `spec`, `mark`, `runs`, `walkthrough`, and `ui`.
* Dashboard on 127.0.0.1:7788 with run replay and watch pages.
* Run history in the project's `.reverie/` directory: `runs/`, `specs/`, `cache/`, and `playbook.json`. `reverie init` creates it and `reverie runs import-legacy` moves old runs into it.
* Storybook with UI concepts for the dashboard, built on shadcn/ui with one theme.

### Documentation

* README with a banner, logo, screenshots, and a demo spec.
