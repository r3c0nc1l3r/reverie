---
id: WL-02
app: widgetlab
session: widgets
role: anonymous
mfa: false
requirement: WL-R2 native dialogs
---
# WL-02 — Delete and rename tasks through browser dialogs

## Goal

Show that confirm and prompt dialogs are handled: a cancelled delete changes nothing, an accepted delete removes the task, and a prompt renames a task.

## Fixtures

- A running WidgetLab with fresh data: four tasks, starting with 'Water the ferns'.
- No sign-in.

## Steps

1. Open 'Tasks' from the top navigation. Check that the page shows '4 tasks'.
2. Set the next browser dialog to be dismissed, then click 'Delete Water the ferns'. Check that the page still shows '4 tasks' and 'Water the ferns'. Then set dialogs back to accept.
3. Click 'Delete Water the ferns' and accept the confirm dialog. Check that the page shows "Deleted 'Water the ferns'." and '3 tasks'.
4. Click 'Rename Oil the bicycle chain' and answer the prompt with 'Oil and adjust the bicycle chain'. Check that the page shows 'Oil and adjust the bicycle chain'.

## Walkthrough

## Evidence

Pass: the dismissed confirm leaves four tasks, the accepted one deletes 'Water the ferns', and the prompt renames the third task.

## Guidance

- The Delete and Rename buttons open native browser dialogs. Use the pilot's dialogs operation to choose accept or dismiss before the click.
- Deleting 'Water the ferns' is intended in step 3 only.

## Cleanup

Restart WidgetLab or run `./reset.sh`.
