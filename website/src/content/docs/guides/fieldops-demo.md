---
title: FieldOps demo
description: A local field-service demo app with five Reverie specs, admin checkpoints, and one deliberate bug.
---

FieldOps is a small field-service app in `examples/fieldops/`. Dispatchers create work orders and schedule them for technicians. Technicians complete the jobs on site. Managers invoice finished jobs. It exists so you can watch Reverie test a realistic app: sign-in, forms, a dispatch board, a status workflow, validation, and one real bug.

The app is local and self-contained. It uses only the Python standard library (`http.server`, `sqlite3`), server-rendered HTML, no JavaScript, and no external services.

## Start the app

Run these from `examples/fieldops`. They need `uv` or Python 3.11 or later.

```bash
cd examples/fieldops
./run.sh                 # http://127.0.0.1:8765/login
./reset.sh               # delete the database and seed it again
./query.sh "select number, status from work_orders"
```

| Script | What it does |
|---|---|
| `run.sh` | Starts the app on `http://127.0.0.1:8765/login`. Set `PORT=9000 ./run.sh` for another port. The first start creates and seeds the database at `app/data/fieldops.db`. |
| `reset.sh` | Deletes the database and writes the seed data again. It is safe while the app runs. |
| `query.sh "SQL"` | Runs one read-only SQL query and prints a header row and one line per row. Used to answer `[admin]` checkpoints. |

Seeded dates are relative to the day of the reset, so reset on the day you test. The specs do not name a host or port, so they work on any `PORT`.

To run a spec you also need Reverie installed ([Installation](/reverie/start/installation/)) and the pilot's model key (`OPENROUTER_API_KEY`) in the environment or in a `.env` file in `examples/fieldops`. See [Configuration](/reverie/reference/configuration/).

## Demo users

These accounts and the shared password are synthetic demo values. They protect nothing.

| Username | Name | Role | Lands on |
|---|---|---|---|
| `dana.dispatch` | Dana Reyes | dispatcher | Dispatch board |
| `tom.tech` | Tomas Nguyen | technician | My jobs |
| `priya.tech` | Priya Shah | technician | My jobs |
| `mia.manager` | Mia Okafor | manager | Work orders |

The password for every account is `fieldops-demo`.

## The intentional bug

FieldOps ships with one deliberate defect, so the suite has a real finding to report. The invoice parts subtotal adds each part's unit price once and ignores the quantity. The invoice lines show the right amounts, but the subtotal and total are too low. Spec FS-04 exposes it. Do not fix it if you want the demo to show a failing test.

## Fixtures

The recipes in `examples/fieldops/fixtures/` cover what a run needs before and during a spec.

| Fixture | Covers |
|---|---|
| `fresh-data.md` | `./reset.sh` before each spec, and the seed records: WO-1001, WO-1006, WO-1007 new and unassigned; WO-1002 and WO-1003 scheduled for Tomas Nguyen today; WO-1004 and WO-1005 scheduled for Priya Shah with one overlap; WO-1008 completed yesterday; WO-1009 invoiced and paid; WO-1010 cancelled. |
| `sign-in.md` | How the orchestrator signs in before the pilot starts, so no spec holds a password. Sessions: `dispatcher` (`dana.dispatch`), `technician` (`tom.tech`), `manager` (`mia.manager`). |
| `db-proof.md` | How to answer an `[admin]` checkpoint with `./query.sh`. Money columns are in cents, times are minutes after midnight, and user ids after a reset are 1 Dana, 2 Tomas, 3 Priya, 4 Mia. |

## The five specs

The specs are in `examples/fieldops/specs/`. Each is one Markdown file in the [spec format](/reverie/guides/writing-specs/). An `[admin]` step becomes a checkpoint for the orchestrator, which answers it with `query.sh`.

| Spec | Session | What it tests | `[admin]` checkpoint |
|---|---|---|---|
| FS-01 Create and dispatch a work order | dispatcher | A new urgent work order reaches the unassigned queue, is assigned to Tomas Nguyen at 15:30, and the customer gets a visit notice. | Step 6: newest work order row (`number, status, priority, technician_id, start_min`). Expect Scheduled, Urgent, technician 2, start 930. |
| FS-02 Technician completes a job | technician | WO-1002 moves to Completed with checklist, parts with quantities, notes, and customer sign-off. The customer gets a completion notice. | None. |
| FS-03 Reschedule from the dispatch board | dispatcher | The board flags the WO-1004 and WO-1005 overlap. Moving WO-1005 to 13:00 clears it. | None. |
| FS-04 Invoice a completed job and mark it paid | manager | INV-5002 charges labor and each part at its quantity, and the payment is recorded. | Step 6: invoice row plus the sum of its part lines. Compare `parts_cents` with `part_lines_cents`. |
| FS-05 Validation errors on the work order form | dispatcher | Missing and invalid input gives inline errors, entered values are kept, and a valid submit creates one work order. | Step 5: work order count and newest row. Expect 11 work orders. |

Expected result on a fresh seed: FS-01, FS-02, FS-03, and FS-05 pass. FS-04 fails at step 3 because of the intentional bug. The pilot records a finding with the expected and actual totals, and the run continues with the payment steps.

## Walkthrough: run FS-01

This runs FS-01 as the dispatcher, from start to review. Run it from `examples/fieldops`, so run history goes to `examples/fieldops/.reverie/`.

### 1. Prepare

```bash
cd examples/fieldops
./reset.sh
./run.sh &
reverie init
```

`reverie init` creates `.reverie/` for runs and stored specs. (`laya-agent` is an older alias for `reverie`.)

### 2. Start a session and sign in

The orchestrator signs in, not the pilot. The password field is hidden from the pilot, and `secret` types it from an environment variable.

```bash
reverie --session dispatcher start --url http://127.0.0.1:8765/login
export FIELDOPS_PASSWORD='fieldops-demo'        # synthetic demo value
reverie --session dispatcher observe            # note the refs of Username and Sign in
reverie --session dispatcher fill <username-ref> --text dana.dispatch
reverie --session dispatcher secret --env FIELDOPS_PASSWORD
reverie --session dispatcher click <sign-in-ref>
reverie --session dispatcher observe            # expect the Dispatch board and 'Dana Reyes'
```

Replace `<username-ref>` and `<sign-in-ref>` with the refs from your own `observe` output.

### 3. Load the spec and run the pilot

```bash
reverie --session dispatcher spec specs/fs-01-create-and-dispatch.md
reverie --session dispatcher pilot
reverie --session dispatcher progress           # poll until the pilot stops
```

The pilot works through steps 1 to 5 in the browser. At step 6 it reaches the `[admin]` step and waits.

### 4. Answer the checkpoint

```bash
reverie --session dispatcher checkpoints        # shows the open checkpoint and its id
./query.sh "select number, status, priority, technician_id, start_min from work_orders order by id desc limit 1"
reverie --session dispatcher resolve <id> done --note "WO-1011 | Scheduled | Urgent | 2 | 930"
reverie --session dispatcher pilot              # continue after the checkpoint
reverie --session dispatcher progress
```

The query prints the newest row. Put that row in the resolve note. The spec expects the new number (WO-1011 after a reset), status Scheduled, priority Urgent, technician 2, and start 930 (15:30).

### 5. Review and clean up

```bash
reverie ui                                      # http://127.0.0.1:7788/
reverie --session dispatcher stop
./reset.sh
```

For FS-02 start a `technician` session signed in as `tom.tech`. For FS-04 use a `manager` session signed in as `mia.manager`. Reset the data before each spec.

After a spec passes, you can write its click-by-click walkthrough into the spec:

```bash
reverie runs list
reverie walkthrough <run-id> --write specs/fs-01-create-and-dispatch.md
```

## Related

- [Examples](/reverie/guides/examples/)
- [Running specs](/reverie/guides/running-specs/)
- [Runs and the dashboard](/reverie/guides/runs-and-dashboard/)
