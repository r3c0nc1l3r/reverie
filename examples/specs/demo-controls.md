---
id: DEMO-01
app: the-internet
session: demo
role: anonymous
mfa: false
requirement: demo
---
# DEMO-01 — Form controls and a loading page

## Goal

Show that the agent can use common form controls and wait for content that loads late, on the public practice site https://the-internet.herokuapp.com.

## Fixtures

None. The site is public and needs no sign-in.

## Steps

1. Open https://the-internet.herokuapp.com/dropdown. Select 'Option 2' in the dropdown list and check that 'Option 2' is the selected value.
2. Open https://the-internet.herokuapp.com/checkboxes. Make sure both checkboxes are checked (checkbox 1 starts unchecked) and check that both are checked.
3. Open https://the-internet.herokuapp.com/dynamic_loading/1. Click Start and check that the page shows 'Hello World!' after the loading bar.

## Evidence

Pass: 'Option 2' selected, both checkboxes checked, and 'Hello World!' shown.

## Guidance

- The Start button is named in step 3; clicking it is intended.

## Cleanup

None.
