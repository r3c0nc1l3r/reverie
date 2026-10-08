---
id: FS-04
app: fieldops
session: manager
role: manager
mfa: false
requirement: FO-R4 invoicing
---
# FS-04 — Invoice a completed job and mark it paid

## Goal

Show that a manager can create an invoice from a completed job, that the invoice charges labor and every part at its quantity, and that the manager can record the payment.

## Fixtures

- Fresh seed data: run `./reset.sh` in `examples/fieldops` before the run (see `fixtures/fresh-data.md`).
- The orchestrator signs in as the manager `mia.manager` (Mia Okafor) before the pilot starts (see `fixtures/sign-in.md`).
- WO-1008 'Replace failed capacitor and filters' is Completed with 2 h labor, 3 × Air filter 16x25 at $12.50, and 1 × Run capacitor at $28.00. The labor rate is $95.00 per hour. The seed holds one invoice, INV-5001.

## Steps

1. Open 'Work orders' from the top navigation, choose the 'Completed' filter, and open WO-1008. Check that Status is 'Completed' and the Parts used table shows AF-1625 with Qty '3' and CAP-45 with Qty '1'.
2. Click Create invoice. Check that the page shows 'Created invoice INV-5002' and the status 'Unpaid'.
3. Read the invoice lines and totals. Check that Labor is '$190.00', the part lines are '$37.50' and '$28.00', Parts subtotal is '$65.50' (the sum of the part lines), and Total due is '$255.50'.
4. Enter Payment reference 'CHK-2231' and click Mark as paid. Check that the page shows 'Marked INV-5002 as paid.', the status 'Paid', and 'reference CHK-2231'.
5. Open WO-1008 from the Job link on the invoice. Check that Status is 'Invoiced' and the Activity list shows 'Marked invoice INV-5002 paid'.
6. [admin] Read invoice INV-5002 and the sum of its part lines from the database: `./query.sh "select i.number, i.labor_cents, i.parts_cents, i.total_cents, i.status, (select sum(wp.qty * p.unit_price_cents) from wo_parts wp join parts p on p.id = wp.part_id where wp.wo_id = i.wo_id) as part_lines_cents from invoices i where i.number = 'INV-5002'"` (run it in examples/fieldops). Report the row and whether parts_cents equals part_lines_cents.

## Walkthrough

## Evidence

Pass: INV-5002 exists, its parts subtotal equals the sum of its part lines ($65.50), the total is labor plus parts ($255.50), the payment is recorded with reference CHK-2231, and WO-1008 is Invoiced. A wrong subtotal or total is a finding and fails step 3; continue with the payment steps.

## Guidance

- Each option of a select list is its own element, named like 'Customer → Lumen Bakery'. Choose an option by acting on that option element without text.
- Create invoice and Mark as paid are the commit buttons of this test; clicking them is intended.
- Compare each amount on the page with the expected value; do not accept a total only because the page shows one.

## Cleanup

Run `./reset.sh` in `examples/fieldops` to restore the seed data.
