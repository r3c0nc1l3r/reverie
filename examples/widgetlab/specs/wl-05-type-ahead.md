---
id: WL-05
app: widgetlab
session: widgets
role: anonymous
mfa: false
requirement: WL-R5 type-ahead suggestions
---
# WL-05 — Pick a color from type-ahead suggestions

## Goal

Show that the stack can type part of a value, wait for suggestions, and pick one.

## Fixtures

- A running WidgetLab.
- No sign-in.

## Steps

1. Open 'Color search' from the top navigation. Type 'la' into Color. Check that the suggestions 'Lavender' and not 'Lime' appear.
2. Click the suggestion 'Lavender', then click Choose. Check that the page shows 'Selected color: Lavender'.

## Walkthrough

## Evidence

Pass: typing 'la' lists Lavender (not Lime), and choosing it shows 'Selected color: Lavender'.

## Guidance

- Suggestions appear a moment after typing; they are list options under the Color field.

## Cleanup

None.
