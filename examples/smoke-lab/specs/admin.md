---
id: smoke-lab-admin
role: admin
purpose: smoke
---

# Smoke lab — admin

## Goal

Confirm that an admin can complete guarded actions while preserving visual evidence for ambiguous controls.

## Fixtures

Use only the local smoke lab. The covered submit, delayed response, missing image, and tiny target are intentional.

## Steps

1. Inspect the submit, arm the obstruction, and verify that Reverie refuses the intercepted click.
2. Remove the obstruction, submit the order, and verify the visible result.
3. Wait for the delayed icon to finish loading, inspect it, and confirm it.
4. Record the broken icon as a real-user failure and verify the visible text workaround.

## Evidence

Keep native observation frames and target crops for the covered, delayed, and broken-icon controls.

## Guidance

Do not use model-driven commands. A DOM label alone does not establish that a user can see or understand a control.
