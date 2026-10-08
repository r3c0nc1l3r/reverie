---
id: WL-04
app: widgetlab
session: widgets
role: anonymous
mfa: false
requirement: WL-R4 tabs and toggles
---
# WL-04 — Change settings across tabs

## Goal

Show that the stack can switch tabs, change a select list and checkboxes in different panels, and save.

## Fixtures

- A running WidgetLab with fresh data: theme Light, weekly digest off, frost alerts on.
- No sign-in.

## Steps

1. Open 'Settings' from the top navigation. Check that the page shows 'Current: theme Light; weekly digest off; frost alerts on.'
2. On the General tab, choose Theme 'Dark'.
3. Open the 'Notifications' tab. Tick 'Weekly digest email' and untick 'Frost alerts'.
4. Click 'Save settings'. Check that the page shows 'Settings saved.' and 'Current: theme Dark; weekly digest on; frost alerts off.'

## Walkthrough

## Evidence

Pass: after Save settings the summary line shows theme Dark, weekly digest on, and frost alerts off.

## Guidance

- Save settings is the commit button of this test; clicking it is intended.
- The Notifications checkboxes are hidden until the Notifications tab is open.

## Cleanup

Restart WidgetLab or run `./reset.sh`.
