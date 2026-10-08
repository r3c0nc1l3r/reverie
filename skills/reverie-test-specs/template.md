---
id: APP-01
app: my-app
---
# APP-01 — One-line title of what the test proves

## Goal

One or two sentences: the user outcome this test proves.

## Fixtures

- Fresh data: how to reset it before the run (for example `./reset.sh`).
- The orchestrator signs in as `demo.user` before the pilot starts (password from an environment variable).
- Known ids, names, or URLs the steps refer to. No secrets.

## Steps

1. Open 'Page name' from the top navigation. Check that the page shows 'Expected heading'.
2. Type 'Exact value' into Field label and click 'Commit button'. Check that the page shows 'Saved.'
3. [admin] Read the new record: `./query.sh "select ..."`. Expected: one row with status 'Active'.

## Walkthrough

## Evidence

Pass: what the run must have shown, in one or two sentences.

## Guidance

- 'Commit button' is the commit button of this test; clicking it is intended.
- Quirks of the page the pilot should know (hover menus, late-loading lists, which of two similar buttons).

## Cleanup

How to restore the data after the run.
