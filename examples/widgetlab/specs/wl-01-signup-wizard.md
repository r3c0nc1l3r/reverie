---
id: WL-01
app: widgetlab
session: widgets
role: anonymous
mfa: false
requirement: WL-R1 multi-step forms
---
# WL-01 — Sign up through the three-step wizard

## Goal

Show that the stack can fill a multi-step form: text fields, a validation error, a radio group, a select list, Back and Next, and a final commit.

## Fixtures

- A running WidgetLab with fresh data: restart it or run `./reset.sh` in `examples/widgetlab`.
- No sign-in.

## Steps

1. Open 'Sign up' from the top navigation. Type 'Robin Vale' into Full name and 'robin.example.org' into Email, then click Next. Check that the page shows 'Enter an email address with an @.' and still shows 'Step 1 of 3'.
2. Replace the Email with 'robin@example.org' and click Next. Check that the page shows 'Step 2 of 3: Choose a plan'.
3. Choose the plan 'Team' and choose Billing 'Yearly', then click Next. Check that the page shows 'Step 3 of 3: Review' and 'Team, billed yearly'.
4. Click Back. Check that the page shows 'Step 2 of 3' with 'Team' still chosen. Click Next again and check that the page shows 'Step 3 of 3: Review'.
5. Click Create account. Check that the page shows 'Welcome, Robin Vale!' and 'Reference: WL-1001'.

## Walkthrough

## Evidence

Pass: the invalid email is refused with an inline error, Back keeps the chosen plan, and the account is created with reference WL-1001.

## Guidance

- Create account is the commit button of this test; clicking it is intended.
- Each option of a select list is its own element, named like 'Billing → Yearly'.

## Cleanup

Restart WidgetLab or run `./reset.sh`.
