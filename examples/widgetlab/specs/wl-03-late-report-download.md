---
id: WL-03
app: widgetlab
session: widgets
role: anonymous
mfa: false
requirement: WL-R3 late content and downloads
---
# WL-03 — Build a report that loads late and download it

## Goal

Show that the stack waits for content that appears after a delay, and that a download lands in the session's download folder.

## Fixtures

- A running WidgetLab with fresh data.
- No sign-in.

## Steps

1. Open 'Reports' from the top navigation. Click 'Build report'. Wait until the page shows 'Report ready: 4 tasks, 12 plantings.' and check that text.
2. Click 'Download CSV'. Check that the page still shows 'Report ready'.
3. [admin] List the session's download folder and report whether it holds garden-report.csv. `ls "$(reverie --session widgets status | sed -n 's/^download_dir: //p')"`

## Walkthrough

## Evidence

Pass: the report appears after the delay and garden-report.csv is in the download folder, not in the user's own Downloads.

## Guidance

- The report takes about three seconds to build; wait for it rather than clicking again.

## Cleanup

Restart WidgetLab or run `./reset.sh`. Delete the session's download folder if you used a temporary one.
