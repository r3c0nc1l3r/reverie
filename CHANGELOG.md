# Changelog

All notable changes to reverie are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) section names, and the
project uses [Semantic Versioning](https://semver.org/). From 0.1.0 on,
[release-please](https://github.com/googleapis/release-please) writes new entries
from the Conventional Commit titles of merged pull requests. Do not edit released
entries by hand.

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
