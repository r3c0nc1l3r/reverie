# Reverie smoke lab

This synthetic fixture lets you inspect guarded actions and visual evidence on a local page. It does not require an account or external service.

From the repository root, start the server:

```bash
python examples/smoke-lab/server.py
```

Open `http://127.0.0.1:8767/`. Pass `--port` to choose a different port. Stop the server with Ctrl+C.

The page includes an obstructed submit button, an icon that loads after 2.5 seconds, a missing image with a visible text fallback, and a tiny low contrast target. The [admin](specs/admin.md) and [support](specs/support.md) specs describe example checks. A semantic label alone does not prove that a sighted user can see or use a control.
