# Fixture: database proof for [admin] checkpoints

An `[admin]` step becomes a checkpoint for the orchestrator. For FieldOps the terminal proof is a read-only query
against the SQLite database:

```bash
cd examples/fieldops
./query.sh "select number, status, technician_id, sched_date, start_min from work_orders order by id"
```

`query.sh` opens the database read-only and prints a header row and one line per row. Report the rows in the
resolve note, for example:

```bash
reverie --session dispatcher resolve <id> done --note "WO-1011 | Scheduled | Urgent | 2 | 930"
reverie --session dispatcher pilot
```

Useful columns: `work_orders.start_min` and `duration_min` are minutes after midnight; money is in cents
(`invoices.parts_cents`, `total_cents`, `parts.unit_price_cents`). User ids after a reset: 1 Dana Reyes, 2 Tomas
Nguyen, 3 Priya Shah, 4 Mia Okafor.
