---
id: FS-05
app: fieldops
session: dispatcher
role: dispatcher
mfa: false
requirement: FO-R5 input validation
---
# FS-05 — Validation errors on the work order form

## Goal

Show that the new work order form rejects missing and invalid input with inline errors, keeps the entered values, and creates the work order once the input is valid.

## Fixtures

- Fresh seed data: run `./reset.sh` in `examples/fieldops` before the run (see `fixtures/fresh-data.md`).
- The orchestrator signs in as the dispatcher `dana.dispatch` (Dana Reyes) before the pilot starts (see `fixtures/sign-in.md`).
- The seed data holds 10 work orders (WO-1001 to WO-1010).

## Steps

1. Open 'New work order' from the top navigation. Leave every field at its default and click Create work order. Check that the page shows 'Fix 3 errors' with 'Choose a customer.', 'Choose a site.', and 'Enter a title.'
2. Choose Customer 'Lumen Bakery', choose Site 'Harbor View — Building A (400 Harbor Road, Unit A)', enter Title 'Leak', enter SLA due date '2020-01-01', and click Create work order. Check that the page shows 'The site must belong to Lumen Bakery.', 'Title must be at least 5 characters.', and 'SLA due date cannot be in the past.'
3. Check that the form kept the entered values: Customer 'Lumen Bakery', Title 'Leak', and SLA due date '2020-01-01'.
4. Choose Site 'Lumen Bakery — 12 Mill Street (12 Mill Street)', replace the Title with 'Leak under the prep sink', clear the SLA due date, and click Create work order. Check that the page shows 'Created work order' with a new WO number, Status 'New', and Priority 'Normal'.
5. [admin] Count the work orders and read the newest one from the database: `./query.sh "select (select count(*) from work_orders) as total, number, title, sla_due from work_orders order by id desc limit 1"` (run it in examples/fieldops). Report the row. Expected: 11 work orders, and the newest has the title 'Leak under the prep sink' and an SLA due date 5 days from today.

## Walkthrough

## Evidence

Pass: the three empty-form errors, the three invalid-input errors with the values kept, one new work order after the valid submit, and the database proof that the invalid submits created nothing.

## Guidance

- Each option of a select list is its own element, named like 'Customer → Lumen Bakery'. Choose an option by acting on that option element without text.
- Create work order is the commit button of this test; clicking it several times is intended.
- The SLA due date is a text field in the format YYYY-MM-DD; an empty value means the priority default.

## Cleanup

Run `./reset.sh` in `examples/fieldops` to restore the seed data.
