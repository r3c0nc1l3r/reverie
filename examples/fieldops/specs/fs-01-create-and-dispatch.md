---
id: FS-01
app: fieldops
session: dispatcher
role: dispatcher
mfa: false
requirement: FO-R1 dispatch
---
# FS-01 — Create and dispatch a work order

## Goal

Show that a dispatcher can create an urgent work order, see it in the unassigned queue, assign it to a technician from the dispatch board, and that the customer gets a visit notice.

## Fixtures

- Fresh seed data: run `./reset.sh` in `examples/fieldops` before the run (see `fixtures/fresh-data.md`).
- The orchestrator signs in as the dispatcher `dana.dispatch` (Dana Reyes) before the pilot starts (see `fixtures/sign-in.md`).
- The seed data holds WO-1001 to WO-1010. The new work order gets the next free number (WO-1011 after a reset).
- Tomas Nguyen already has two jobs today: 08:00–10:00 and 13:00–15:00.

## Steps

1. Open 'New work order' from the top navigation. Choose Customer 'Lumen Bakery', choose Site 'Lumen Bakery — 12 Mill Street (12 Mill Street)', enter Title 'Walk-in cooler not holding temperature', choose Priority 'Urgent', leave SLA due date empty, and click Create work order. Check that the page shows 'Created work order' with a new WO number and the status 'New'.
2. Open 'Dispatch board' from the top navigation. Check that the new work order is in the Unassigned column with the title 'Walk-in cooler not holding temperature'.
3. In the 'Assign or reschedule' form, choose the new work order in Work order, choose Technician 'Tomas Nguyen', keep Day as today, choose Start time '15:30', keep Duration '2 h', and click Save assignment. Check that the page shows 'Saved the assignment for' the new number and that the job is in the Tomas Nguyen column at '15:30–17:30' with no conflict flag.
4. Open the new work order by its number. Check that Status is 'Scheduled', Technician is 'Tomas Nguyen', and the Activity list shows 'Assigned to Tomas Nguyen'.
5. Open 'Notifications' from the top navigation. Check that the newest notice is 'Visit scheduled:' for the new number, sent to 'owner@lumenbakery.example'.
6. [admin] Read the newest work order from the database: `./query.sh "select number, status, priority, technician_id, start_min from work_orders order by id desc limit 1"` (run it in examples/fieldops). Report the row. Expected: the new number, status Scheduled, priority Urgent, technician_id 2 (Tomas Nguyen), start_min 930 (15:30).

## Walkthrough

## Evidence

Pass: a new WO number with status New after step 1, the card in Unassigned, the saved assignment at 15:30–17:30 for Tomas Nguyen without a conflict flag, status Scheduled with the activity entry, the 'Visit scheduled' notice to the customer, and the database row from step 6.

## Guidance

- Each option of a select list is its own element, named like 'Customer → Lumen Bakery'. Choose an option by acting on that option element without text.
- Create work order and Save assignment are the commit buttons of this test; clicking them is intended.
- The Work order list in the assign form shows each option as 'WO-number — title (status)'.
- Start time and Duration are select lists, not free text.
- Do not use Cancel work order.

## Cleanup

Run `./reset.sh` in `examples/fieldops` to restore the seed data.
