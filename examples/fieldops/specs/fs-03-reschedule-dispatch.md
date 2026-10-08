---
id: FS-03
app: fieldops
session: dispatcher
role: dispatcher
mfa: false
requirement: FO-R3 schedule conflicts
---
# FS-03 — Reschedule from the dispatch board

## Goal

Show that the dispatch board flags overlapping jobs for one technician, and that a dispatcher can clear the conflict by rescheduling one job from the board.

## Fixtures

- Fresh seed data: run `./reset.sh` in `examples/fieldops` before the run (see `fixtures/fresh-data.md`).
- The orchestrator signs in as the dispatcher `dana.dispatch` (Dana Reyes) before the pilot starts (see `fixtures/sign-in.md`).
- Today Priya Shah has WO-1004 at 09:00–11:00 and WO-1005 at 10:00–12:00. They overlap, so the seed starts with one conflict.

## Steps

1. Open 'Dispatch board' from the top navigation. Check that the page shows '1 schedule conflict on this day' and that WO-1005 in the Priya Shah column shows 'Conflict with WO-1004'.
2. Click the link 'Reschedule WO-1005' on the WO-1005 card. Check that the 'Assign or reschedule' form shows Work order WO-1005 selected, Technician 'Priya Shah', and Start time '10:00'.
3. In the same form, choose Start time '13:00' and keep the other values. Click Save assignment. Check that the page shows 'Saved the assignment for WO-1005.' and that the WO-1005 card shows '13:00–15:00'.
4. Check that the page no longer shows 'schedule conflict' and that no card shows 'Conflict with'.
5. Open WO-1005 by its number. Check that the Activity list shows 'Rescheduled from Priya Shah' with 'at 13:00'.

## Walkthrough

## Evidence

Pass: the conflict is flagged before the change; after Save assignment WO-1005 is at 13:00–15:00, no conflict banner or flag remains, and the activity log records the reschedule.

## Guidance

- Each option of a select list is its own element, named like 'Customer → Lumen Bakery'. Choose an option by acting on that option element without text.
- Save assignment is the commit button of this test; clicking it is intended.
- The Reschedule link fills the form below the board; scroll down to reach it.
- Do not change the technician or the day.

## Cleanup

Run `./reset.sh` in `examples/fieldops` to restore the seed data.
