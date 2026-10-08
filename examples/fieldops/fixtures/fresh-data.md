# Fixture: fresh seed data

Every FieldOps spec starts from the seed data. Reset it before each run and again after it.

```bash
cd examples/fieldops
./reset.sh
```

`reset.sh` deletes `app/data/fieldops.db` and writes the seed again. It is safe while the app runs; the app opens
the database for each request. Seeded dates are relative to the day of the reset, so reset on the day you run.

What the seed holds (today = the day of the reset):

| Record | State |
|---|---|
| WO-1001, WO-1006, WO-1007 | New, unassigned |
| WO-1002 | Scheduled, Tomas Nguyen, today 08:00–10:00 (used by FS-02) |
| WO-1003 | Scheduled, Tomas Nguyen, today 13:00–15:00 |
| WO-1004, WO-1005 | Scheduled, Priya Shah, today 09:00–11:00 and 10:00–12:00: one conflict (used by FS-03) |
| WO-1008 | Completed yesterday, 2 h labor, 3 × AF-1625 and 1 × CAP-45 (used by FS-04) |
| WO-1009 / INV-5001 | Invoiced and paid |
| WO-1010 | Cancelled |
