---
id: FS-02
app: fieldops
session: technician
role: technician
mfa: false
requirement: FO-R2 field work
---
# FS-02 — Technician completes a job with parts and customer sign-off

## Goal

Show that a technician can take a scheduled job through En route and In progress to Completed, record the checklist, parts with quantities, notes, and the customer sign-off, and that the customer gets a job-completed notice.

## Fixtures

- Fresh seed data: run `./reset.sh` in `examples/fieldops` before the run (see `fixtures/fresh-data.md`).
- The orchestrator signs in as the technician `tom.tech` (Tomas Nguyen) before the pilot starts (see `fixtures/sign-in.md`).
- WO-1002 'No heat in the lobby' is scheduled for Tomas Nguyen today at 08:00 with status Scheduled.

## Steps

1. Open 'My jobs' from the top navigation and open 'WO-1002 — No heat in the lobby' under Today. Check that the job page shows Status 'Scheduled'.
2. Click Start travel. Check that the page shows 'Travel started.' and Status 'En route'.
3. Click Arrive on site. Check that the page shows 'Arrived on site.' and Status 'In progress'.
4. Tick all five checklist items and click Save checklist. Check that the page shows 'Checklist saved.' and '5 of 5 done'.
5. In Parts used, choose Part 'Air filter 16x25 (AF-1625) — $12.50', enter Quantity '2', and click Add part. Check that the Parts used table has a row for AF-1625 with Qty '2' and Line total '$25.00'.
6. Choose Part 'Condensate pump (CP-120) — $89.00', enter Quantity '1', and click Add part. Check that the Parts used table has a row for CP-120 with Qty '1' and Line total '$89.00'.
7. Enter Job notes 'Replaced clogged filters and the condensate pump.' and click Save notes. Check that the page shows 'Notes saved.'
8. Enter Labor hours '1.5', enter Customer name (signature) 'Alex Morgan', tick 'The customer confirms the work is complete', and click Complete job. Check that the page shows 'Job WO-1002 completed.', Status 'Completed', and 'Signed by Alex Morgan'.
9. Open 'Notifications' from the top navigation. Check that a notice 'Job completed: WO-1002' was sent to 'facilities@harborview.example' and names 'Alex Morgan'.

## Walkthrough

## Evidence

Pass: the status moves Scheduled, En route, In progress, Completed; the checklist shows 5 of 5 done; the parts table shows AF-1625 × 2 ($25.00) and CP-120 × 1 ($89.00); the sign-off names Alex Morgan; and the job-completed notice is addressed to the customer.

## Guidance

- Each option of a select list is its own element, named like 'Customer → Lumen Bakery'. Choose an option by acting on that option element without text.
- Start travel, Arrive on site, Save checklist, Add part, Save notes, and Complete job are the intended commit buttons.
- Quantity is a text field; clear it before you type the value.
- Do not click Remove in the parts table.

## Cleanup

Run `./reset.sh` in `examples/fieldops` to restore the seed data.
