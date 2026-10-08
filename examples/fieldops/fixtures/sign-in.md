# Fixture: orchestrator sign-in

Sign-in is a precondition, not a spec step. The orchestrator signs in before it starts the pilot, so no spec holds
a password and the pilot never sees one. The password field is hidden from the pilot on purpose; `secret` types
it from an environment variable.

The demo accounts and their shared password are synthetic demo values (see the FieldOps README).

| Session | Username | Role | Used by |
|---|---|---|---|
| dispatcher | `dana.dispatch` | dispatcher | FS-01, FS-03, FS-05 |
| technician | `tom.tech` | technician | FS-02 |
| manager | `mia.manager` | manager | FS-04 |

```bash
export FIELDOPS_PASSWORD='fieldops-demo'            # synthetic demo value
reverie --session dispatcher start --url http://127.0.0.1:8765/login
reverie --session dispatcher observe                 # find the refs of Username and Sign in
reverie --session dispatcher fill <username-ref> --text dana.dispatch
reverie --session dispatcher secret --env FIELDOPS_PASSWORD
reverie --session dispatcher click <sign-in-ref>
reverie --session dispatcher observe                 # expect the Dispatch board and 'Dana Reyes'
```

A signed-in dispatcher or manager lands on the Dispatch board or Work orders; a technician lands on My jobs.
