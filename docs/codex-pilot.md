# Codex pilot

Reverie can run its pilot on `gpt-6.1-terra` through an existing Codex ChatGPT sign-in. It starts the installed [Codex app-server](https://developers.openai.com/codex/app-server) and uses its stdio JSON-RPC interface. Reverie does not read or copy Codex authentication files. It does not make direct requests with subscription tokens.

## Setup

Run `codex login status` on the machine that runs Reverie. If it is not signed in with ChatGPT, run `codex login` there. Do not copy authentication files from another machine.

Set these variables:

```sh
export REVERIE_PILOT_PROVIDER=codex
export REVERIE_PILOT_MODEL=gpt-6.1-terra
```

The existing `LAYA_AGENT_PILOT_PROVIDER` and `LAYA_AGENT_PILOT_MODEL` aliases still work. The `REVERIE_` names win. Set the model explicitly to replace an existing GLM model in an environment file.

`REVERIE_CODEX_COMMAND` selects the executable. Its default is `codex`. `REVERIE_CODEX_TIMEOUT` sets a positive call timeout in seconds. Its default is 120. HTTP base URLs and API keys do not apply to the Codex provider.

The text helper can use the same route:

```sh
export TEXT_MODEL_PROVIDER=codex
export TEXT_MODEL=gpt-6.1-terra
```

This covers escalation, goal planning, field values, and recaps. The pilot's image-based UI review also uses Codex. Jev remains a separate decision engine. For a stack with local decisions, use `REVERIE_DECISION_ENGINE=laya` with the local Laya service. A pilot that acts directly can start without a Jev key when Jev was not explicitly selected.

## Runtime

One app-server process serves a run. It keeps separate ephemeral threads for each role, instruction set, and model. The pilot reuses its thread across decisions. Calls are serialized within a daemon. Separate Reverie daemons have separate processes and browser profiles.

The child has an empty temporary working directory and a read-only sandbox. Shell, execution, plugins, apps, hooks, web search, and other model tools are disabled. Inherited MCP servers are disabled by name before thread creation. Tool and approval requests are refused. The child returns decisions. Reverie's guarded executor performs browser actions.

Screenshots travel as inline image inputs. The pilot receives the same marked image and coordinate mapping as other providers. Visual actions still require a fresh frame, node guards, and a final hit-test.

Output must parse as a JSON object and pass the existing operation validator. The protocol does not expose a per-turn output-token limit. Reverie accepts `max_tokens` for interface compatibility and uses a deadline to bound the call. Login, quota, timeout, malformed output, and invalid-operation errors stop the run after one attempt. Error messages use known categories and do not include raw server output.

A new plan resets the provider. Closing a session blocks new provider calls, interrupts the active call, and waits for the pilot before browser cleanup. A new plan explicitly resumes the provider for the next run.
