# FieldOps suite

Five Reverie specs that test the FieldOps demo app end to end. Each spec is one Markdown file; its steps become
the pilot's plan, and each `[admin]` step becomes a checkpoint for the orchestrator.

| Spec | Session / role | What it proves | Admin proof |
|---|---|---|---|
| [FS-01](fs-01-create-and-dispatch.md) Create and dispatch a work order | dispatcher | A new urgent work order reaches the queue, is assigned to Tomas Nguyen at 15:30, and the customer gets a visit notice | Newest work order row |
| [FS-02](fs-02-technician-completes-job.md) Technician completes a job | technician | WO-1002 moves to Completed with the checklist, parts with quantities, notes, and customer sign-off; the customer gets a completion notice | None |
| [FS-03](fs-03-reschedule-dispatch.md) Reschedule from the dispatch board | dispatcher | The board flags the WO-1004 / WO-1005 overlap; rescheduling WO-1005 to 13:00 clears it | None |
| [FS-04](fs-04-invoice-and-payment.md) Invoice a completed job and mark it paid | manager | INV-5002 charges labor and each part at its quantity, and the payment is recorded | Invoice row and sum of part lines |
| [FS-05](fs-05-work-order-validation.md) Validation errors on the work order form | dispatcher | Missing and invalid input gives inline errors, values are kept, and a valid submit creates one work order | Work order count |

Expected result on a fresh seed: FS-01, FS-02, FS-03, and FS-05 pass. **FS-04 fails at step 3** because of the
intentional invoice defect (see the FieldOps README). That failure is the point of the demo: the pilot records a
finding with the expected and actual totals, and the run continues with the payment steps.

## Before each spec

1. `./reset.sh` ([fixtures/fresh-data.md](../fixtures/fresh-data.md)).
2. Start a session for the spec's role and sign in ([fixtures/sign-in.md](../fixtures/sign-in.md)).
3. Load the spec and start the pilot; resolve `[admin]` checkpoints with a query ([fixtures/db-proof.md](../fixtures/db-proof.md)).

The specs do not name the host or port. They start from the top navigation of the signed-in app, so they work on
any `PORT`.

## Walkthroughs

A spec's `## Walkthrough` section is empty until a run passes. Then write it from the run:

```bash
reverie runs list
reverie walkthrough <run-id> --write specs/fs-01-create-and-dispatch.md
```
