"""Pilot: a smarter, still inexpensive model that runs a whole test plan so the orchestrator stays high level.

Layers, bottom up:
  Laya     local typed decisions for each click or keystroke
  Mercury  overrules Laya when Laya is unsure, looping, or off-goal
  Pilot    (default z-ai/glm-5.3-flash) turns each plan step into intents for the Laya/Mercury stack,
           verifies results with checks, marks steps, and moves between tabs and sites
  Orchestrator  starts tests, resolves admin checkpoints (database, logs, mail API, secrets), reviews verdicts

The pilot never gets a selector, a shell, or a secret. Each answer is one operation, validated before it runs.
"""

import json
import os
import re
import time
from urllib.parse import urlparse

from .. import model

DEFAULT_MODEL = "z-ai/glm-5.3-flash"

PILOT = """You are the pilot of a QA browser test. You run the test plan one operation at a time. Fast layers below
you (Laya, then Mercury) click and type; you give them short, concrete intents and verify the outcome.

Answer with JSON only, one operation:
{"op": "do", "intent": "<one concrete UI goal, e.g. Open Dispatch then Work Order>", "hints": ["<optional
   steering: field names, which button>"], "until_text": "<optional text that means done>",
   "until_url": "<optional url fragment that means done>", "avoid": ["<labels the stack must never click here,
   e.g. Forgot password?, a site logo>"], "allow_values": ["<exact values the stack may type for this intent>"],
   "max_steps": <1-10, how many clicks/keystrokes this intent should need>,
   "read_only": <true when the intent only navigates or inspects; then nothing can be typed or selected>}
{"op": "act", "ref": "<element id you can see in the screenshot>", "text": "<value to type, fill fields only; '' clears the field>"}
   (you act directly; use it when the stack failed twice on a target, or the target is visual: icons,
   suggestion rows, custom widgets. The screenshot marks each element with its id in a yellow tag.)
{"op": "check", "text": "<text that must be on the page>", "absent": "<text that must not be>", "url": "<url part>",
   "link": "<visible link text>", "href": "<part the link's target must contain, e.g. token=>"}
   (a link check reads link targets without showing them; use it instead of opening source views)
{"op": "tab_new", "url": "<http(s) url>", "isolated": <true for a signed-out tab with its own cookies>}
{"op": "tab", "index": <n from the tabs list>}
{"op": "dialogs", "answer": "accept|dismiss", "text": "<optional: the value an accepted prompt dialog returns>"}
   (how the next native confirm and prompt dialogs are answered; default accept. Set dismiss before a click whose
   confirm you must cancel, then set accept again. Set text before a click that opens a prompt you must fill)
{"op": "back"}  (the browser Back button; use it when a step says Back or to return to the previous page state)
{"op": "goto", "url": "<http(s) url on a host already open or named in the plan or notes>"}
{"op": "mark", "status": "pass|fail|blocked", "note": "<evidence: what you saw that proves it>"}
{"op": "admin", "need": "<what the orchestrator must do from a terminal: a database read, a mail API lookup,
   a log read, a sign-in with a secret, a fixture reset; say exactly what result you need back>"}
{"op": "finding", "severity": "high|medium|low", "what": "<what is wrong, one sentence>",
   "expected": "<what the plan or a user expects>", "actual": "<what the app did>", "workaround": "<how you got past it, or null>"}
   (records a defect or deviation without stopping the test; see the failure rules below)
{"op": "lesson", "host": "<site host>", "lesson": "<a durable, reusable rule for this site learned from a
   failure, e.g. 'Mailpit bodies are iframes; open /view/<ID>.html to click links' or 'On /login the submit
   button is Sign in; never click the logo'>"}
{"op": "ask", "question": "<only when the plan is ambiguous and nothing else helps>"}
Always add "reason": "<one short sentence for the on-screen caption>".
Always add "ui": null, or one sentence describing anything in the screenshot a real user would find broken:
content not rendering, a control that did not respond when the recent actions clicked it, overlapping or
clipped elements, error text, raw code, wrong data. Look at every screenshot like a user would.
Optionally add "say": a pleasant, spoken progress update for the tester who is listening. Use it only at
milestones: starting a step, finishing a step (the bottom line and whether it passed), or a notable finding.
Speak like a colleague giving a status update, first person, one or two short sentences, e.g. "I found the
invoice email for work order 12 and its approve link carries a token. Step three passes." Never read out checks,
element names, URLs, or field values; never mention the orchestrator or pausing. Most operations have no "say".

Rules:
- Failures are results, not obstacles. When the app does not do what the step or a user expects (an item is
  missing from a list, a control is absent or does nothing, a wrong value, an error), record a finding FIRST.
  If you then work around it to continue (for example open a work order by URL because it is missing from the
  dispatch board), put the workaround in the finding. A step with a medium or high finding must be marked fail, with
  the finding in the note. After you mark a step fail, continue with the next step; the run does not stop.
- Read "stack ran" in each outcome: it lists every action the stack executed. Check it did only what you
  asked. If it did more (for example clicked Yes or Save), record that and verify the resulting state.
- Committing clicks (Yes, OK, Confirm, Delete, Save, Submit, Cancel Order, Edit Details, ...) run only when
  your intent names them. Split "open the dialog" and "confirm the dialog" into separate intents.
- Never repeat an intent that already failed on this step. After one failure, change the approach (different
  control, hint, route) or judge it: record a finding and mark fail, or ask. The context warns you when you
  are repeating yourself or making no progress.
- Before a step, make sure you are on the page it starts from (for example client HOME or NEW ORDER). If the
  tab shows some other record or form, navigate first; never reuse a form that belongs to another record.
- A step that creates something is proven only by something NEW: an ID or row that did not exist before this
  run and is not named in the notes as an existing fixture. An existing ID is not proof of creation.
- Work on current_step only. When its outcome is proven, mark it; the next step starts automatically.
- Put any value to type in single quotes inside the intent, e.g. Enter '300' in Client billing (client_rate2).
  Use field names and hints from the elements list; they are stable.
- One intent per UI goal. If the stack paused without reaching it, rephrase with more specific hints, or split it.
  After two failed tries on the same goal, use admin or ask.
- When you mark a step, a visual UI review of the step's screenshots runs; its findings appear in ui_reviews.
  If a high-severity UI problem affects the step's feature, mark the step fail even if the data checks passed.
  Also look at the screenshot you get each turn; call out broken UI in your note or say.
- Mark pass only after a check you ran in this step passed and proves the step. Mark fail when a check proves the
  wrong outcome. Mark blocked when the environment prevents the test (missing data, an error you cannot pass).
- Never guess secrets, codes, tokens, or passwords, and never put a token in a note. Use admin for sign-in secrets.
- Answers to earlier admin requests are in checkpoints; use them as evidence.
- Native dialogs (confirm, alert, prompt) are answered automatically (accept by default; see the dialogs operation);
  their text and the answer given are in recent_dialogs.
- When the stack pauses as blocked, read its reason in your recent operations and decide yourself: the page may
  already show the expected outcome. Use admin only for real terminal work.
- Tabs marked signed_out_isolated have no sign-in. Do admin or signed-in work only in a tab that is not isolated;
  a login page in an isolated tab does not mean the session expired.
- Prefer the page you are on. Use tab_new with isolated true when a step says signed out or private window."""

OPS = {"finding", "dialogs", "back", "act", "do", "check", "tab_new", "tab", "goto", "mark", "admin", "ask", "lesson"}


def playbook_path():
    from .project import playbook_path as project_playbook

    return project_playbook()


def load_playbook():
    try:
        return json.loads(playbook_path().read_text())
    except (OSError, ValueError):
        return {}


def add_lesson(host, lesson, test=None):
    """Lessons persist across tests and sessions, keyed by host; duplicates are dropped."""
    book = load_playbook()
    entries = book.setdefault(host, [])
    if any(e["lesson"].strip().lower() == lesson.strip().lower() for e in entries):
        return False
    entries.append({"lesson": lesson.strip(), "test": test, "added": time.strftime("%Y-%m-%dT%H:%M:%S")})
    book[host] = entries[-30:]
    path = playbook_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(book, indent=2))
    return True


def lessons_for(hosts):
    book = load_playbook()
    return {h: [e["lesson"] for e in book.get(h, [])] for h in hosts if book.get(h)}


def pilot_model():
    return os.environ.get("LAYA_AGENT_PILOT_MODEL", DEFAULT_MODEL)


def context_for(session, step, log):
    page = session.page or {}
    test = session.test or {}
    actions = page.get("actions", [])
    # A text field's 'Open …' click twin only focuses it; leave it out so long forms fit (the fill element stays).
    fills = {(a.get("label"), a.get("hint")) for a in actions if a["kind"] == "fill"}
    actions = [a for a in actions if not (a["kind"] == "click" and a.get("role") == "textbox"
                                          and ((a.get("label") or "").removeprefix("Open "), a.get("hint")) in fills)]
    elements = [{k: a[k] for k in ("id", "kind", "label", "value", "hint", "checked", "offscreen")
                 if a.get(k) not in (None, "")} for a in actions[:220]]
    from .session import scrub

    return scrub({
        "test": test.get("title"),
        "plan": [{"n": s["n"], "title": s["title"], "status": s["status"], "note": s["note"]}
                 for s in test.get("steps", [])],
        "current_step": {"n": step["n"], "title": step["title"]},
        "notes": session.notes[-12:],
        "playbook": lessons_for({urlparse(t["url"]).hostname for t in tab_list(session)}),
        "checkpoints": [{k: c.get(k) for k in ("title", "status", "result")} for c in session.checkpoints[-6:]],
        "your_recent_operations": log[-12:],
        "warnings": warnings_for(step, log, session),
        "recent_actions": [{k: h.get(k) for k in ("kind", "label", "text", "by")} for h in session.history[-12:]],
        "recent_checks": session.checks[-4:],
        "recent_dialogs": session.dialogs[-3:],
        "ui_reviews": [{"step": st["n"], **st["ui"]} for st in test.get("steps", []) if st.get("ui")],
        "tabs": [{"index": i, "title": t["title"][:80], "url": t["url"][:200], "current": t["current"],
                  "signed_out_isolated": t.get("isolated", False)} for i, t in enumerate(tab_list(session))],
        "url": page.get("url"),
        "title": page.get("title"),
        "visible_text": page.get("text", "")[:5000],
        "elements": elements,
    })


def warnings_for(step, log, session):
    """Tell the pilot when it repeats itself or stalls, so it judges instead of looping."""
    mine = [e for e in log if e.get("step") == step["n"]]
    notes = []
    intents = [" ".join(re.findall(r"[a-z0-9]+", (e.get("intent") or "").lower())) for e in mine if e.get("op") == "do"]
    repeated = {i for i in intents if i and intents.count(i) > 1}
    if repeated:
        notes.append("You already issued this intent more than once on this step: " + "; ".join(sorted(repeated))[:200]
                     + ". Do not repeat it: change the approach, or record a finding and mark the step fail.")
    acts = [(e.get("ref"), e.get("text") or "") for e in mine if e.get("op") == "act"]
    looped = {a for a in acts if acts.count(a) > 1}
    if looped:
        notes.append("You repeated the same act on this step: " + "; ".join(f"{r} text={t!r}" for r, t in sorted(looped))[:200]
                     + ". It changed nothing. To type into a field, act on its fill element (kind fill) and give the "
                     "text; a click element named 'Open …' only focuses it. Otherwise record a finding and mark fail.")
    ops = (step.get("progress") or {}).get("ops", 0)
    if ops >= 6:
        notes.append(f"{ops} operations on this step without a new passing check. Decide now: prove the step with a "
                     "check, record a finding and mark fail, or ask.")
    return notes


def tab_list(session):
    return [t for t in session.browser.tabs() if t["url"] != "about:blank"]


def allowed_hosts(session):
    hosts = {urlparse(t["url"]).hostname for t in tab_list(session)}
    text = " ".join([(session.test or {}).get("title", "")] + [s["title"] for s in (session.test or {}).get("steps", [])]
                    + session.notes + [((c.get("result") or {}).get("note") or "") for c in session.checkpoints])
    hosts |= {urlparse(u).hostname for u in re.findall(r"https?://[^\s)\]'\"<>,;]+", text)}
    return {h for h in hosts if h}


def validate(output, session):
    if isinstance(output, dict) and output.get("op") == "wait":
        # Models often answer a loading page with a bare wait; it means the observed "wait" action.
        output = {**output, "op": "act", "ref": "wait"}
    if not isinstance(output, dict) or output.get("op") not in OPS:
        raise ValueError(f"Pilot returned no valid operation: {str(output)[:200]}")
    op = output["op"]
    ui = output.get("ui")
    clean = {"op": op, "reason": str(output.get("reason") or "")[:240],
             "ui": str(ui).strip()[:300] if isinstance(ui, str) and ui.strip() and ui.strip().lower() != "null" else None,
             "say": str(output.get("say") or "").strip()[:300] or None}
    if op == "do":
        intent = output.get("intent")
        if not isinstance(intent, str) or not intent.strip():
            raise ValueError("Pilot gave an empty intent")
        try:
            max_steps = min(10, max(1, int(output.get("max_steps") or 6)))
        except (TypeError, ValueError):
            max_steps = 6
        clean.update(intent=intent.strip()[:400],
                     hints=[str(h)[:200] for h in (output.get("hints") or []) if h][:4],
                     until_text=output.get("until_text") or None, until_url=output.get("until_url") or None,
                     avoid=[str(a)[:120] for a in (output.get("avoid") or []) if a][:8],
                     allow_values=[str(v)[:200] for v in (output.get("allow_values") or []) if v][:8],
                     max_steps=max_steps, read_only=bool(output.get("read_only")))
    elif op == "finding":
        if output.get("severity") not in {"high", "medium", "low"} or not str(output.get("what") or "").strip():
            raise ValueError("A finding needs a severity (high|medium|low) and what")
        clean.update({k: str(output.get(k) or "")[:300] or None for k in ("what", "expected", "actual", "workaround")},
                     severity=output["severity"])
    elif op == "lesson":
        host, lesson = str(output.get("host") or "").strip(), str(output.get("lesson") or "").strip()
        if not host or not lesson:
            raise ValueError("A lesson needs a host and text")
        clean.update(host=host[:120], lesson=lesson[:400])
    elif op == "act":
        ref = str(output.get("ref") or "").lstrip("@")
        action = next((a for a in (session.page or {}).get("actions", []) if a["id"] == ref), None)
        if not action:
            raise ValueError(f"Pilot chose {ref!r}, which is not on the page")
        text = output.get("text")
        if action["kind"] != "fill" and isinstance(text, str) and action.get("role") == "textbox":
            # The 'Open …' click twin of a text field only focuses it; typing goes to its fill element.
            base = (action.get("label") or "").removeprefix("Open ")
            twin = next((a for a in (session.page or {}).get("actions", []) if a["kind"] == "fill"
                         and a.get("label") == base and a.get("hint") == action.get("hint")), None)
            if twin:
                ref, action = twin["id"], twin
        if action["kind"] == "select" and isinstance(text, str) and text.strip():
            # Text on a select option means "choose this option": use the sibling option whose name matches.
            field = (action.get("label") or "").split(" → ")[0]
            option = next((a for a in (session.page or {}).get("actions", []) if a["kind"] == "select"
                           and a.get("node", object()) == action.get("node", object())
                           and (a.get("label") or "").split(" → ")[0] == field
                           and (a.get("label") or "").split(" → ")[-1].strip().lower() == text.strip().lower()), None)
            if option:
                ref, action, text = option["id"], option, None
        if action["kind"] == "fill" and text == "":
            pass  # An explicit clear of a field.
        elif action["kind"] == "fill":
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Pilot chose a text field without a value; use text '' to clear it")
            stated = " ".join([s["title"] for s in (session.test or {}).get("steps", [])] + session.notes).lower()
            if text.strip().lower() not in stated:
                raise ValueError(f"Pilot would type {text!r}, which the plan and notes do not state")
        else:
            if isinstance(text, str) and text.strip():
                raise ValueError(f"{ref} is a {action['kind']} target and does not take text; act on the field's "
                                 "fill element to type")
            text = None
        clean.update(ref=ref, text=text, label=action.get("label"))
    elif op == "check":
        fields = {k: output.get(k) for k in ("text", "absent", "url", "link", "href") if output.get(k)}
        if not fields:
            raise ValueError("Pilot check names nothing to check")
        clean.update(fields)
    elif op in {"tab_new", "goto"}:
        url = str(output.get("url") or "")
        if not url.startswith(("http://", "https://")):
            raise ValueError("Pilot URL must be http(s)")
        if op == "goto" and urlparse(url).hostname not in allowed_hosts(session):
            raise ValueError("Pilot may only go to hosts already open or named in the plan or notes")
        clean.update(url=url, isolated=bool(output.get("isolated")))
    elif op == "dialogs":
        if output.get("answer") not in {"accept", "dismiss"}:
            raise ValueError("dialogs answer must be accept or dismiss")
        text = output.get("text")
        text = text.strip() if isinstance(text, str) and text.strip() else None
        if text is not None:
            stated = " ".join([s["title"] for s in (session.test or {}).get("steps", [])] + session.notes).lower()
            if text.lower() not in stated:
                raise ValueError(f"Pilot would answer a prompt with {text!r}, which the plan and notes do not state")
        clean.update(answer=output["answer"], text=text)
    elif op == "tab":
        index = output.get("index")
        if not isinstance(index, int) or not 0 <= index < len(tab_list(session)):
            raise ValueError("Pilot chose a tab that is not open")
        clean["index"] = index
    elif op == "mark":
        if output.get("status") not in {"pass", "fail", "blocked"}:
            raise ValueError("Pilot mark status must be pass, fail, or blocked")
        clean.update(status=output["status"], note=str(output.get("note") or "")[:400])
    elif op == "admin":
        clean["need"] = str(output.get("need") or clean["reason"] or "Orchestrator action needed")[:300]
    elif op == "ask":
        clean["question"] = str(output.get("question") or "")[:300] or "The pilot needs a decision"
    return clean


UI_REVIEW = """You review screenshots from one step of a QA browser test for broken or degraded UI. The images are in
time order; the last one is the step's final screen. Report only problems a user would notice:
overlapping or clipped elements, cut-off or overflowing text, broken images or icons, missing styles (raw
unstyled HTML), error banners or stack traces, raw template code (e.g. #variable# or {{x}}), empty regions where
content should be, misaligned or unreadable controls, dialogs covering content, obviously wrong data (NaN,
undefined, 1/1/1900). Do not report normal design choices, dense legacy layouts, or the yellow agent caption box.
Earlier images show intermediate states (before a save, before a list reloads). Judge whether an action worked only
from the LAST image; report an earlier image only for rendering problems visible in it.

Answer with JSON only: {"issues": [{"severity": "high|medium|low", "image": <1-based index>,
"what": "<one sentence: what is broken and where>"}], "summary": "<one short sentence>"}
Use high for anything that blocks or misleads a user, medium for clearly broken but usable, low for cosmetic."""


def ui_review(session, step, files):
    """Multimodal review of a step's frames. Returns {"issues": [...], "summary": "..."} or None."""
    if os.environ.get("LAYA_AGENT_UI_REVIEW", "1") == "0" or not files:
        return None
    import base64
    import io

    from PIL import Image

    images = []
    for name in files[-5:]:
        try:
            image = Image.open(session.trail_dir / "frames" / name).convert("RGB")
        except OSError:
            continue
        if image.width > 1280:
            image = image.resize((1280, round(image.height * 1280 / image.width)))
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=70)
        images.append(base64.b64encode(out.getvalue()).decode())
    if not images:
        return None
    context = {"test": (session.test or {}).get("title"), "step": step["title"], "images": len(images)}
    try:
        output, _ = model.chat_json(UI_REVIEW, context, model=pilot_model(), max_tokens=4096, role="pilot",
                                    reasoning_effort=os.environ.get("TEXT_MODEL_EFFORT", "low"), images=images)
    except (ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError):
        return None
    issues = []
    for issue in output.get("issues") or []:
        if not isinstance(issue, dict) or issue.get("severity") not in {"high", "medium", "low"}:
            continue
        index = issue.get("image") if isinstance(issue.get("image"), int) else len(images)
        index = min(max(index, 1), len(images))
        issues.append({"severity": issue["severity"], "what": str(issue.get("what") or "")[:300],
                       "frame": files[-len(images):][index - 1]})
    return {"issues": issues, "summary": str(output.get("summary") or "")[:300]}


def marked_screenshot(session, width=1280):
    """The current frame with a yellow id tag on every on-screen control (set-of-marks) for the vision pilot."""
    if not session.frame or os.environ.get("LAYA_AGENT_PILOT_VISION", "1") == "0":
        return None
    import base64
    import io

    from PIL import Image, ImageDraw

    image = Image.open(io.BytesIO(base64.b64decode(session.frame))).convert("RGB")
    draw = ImageDraw.Draw(image)
    seen = set()
    for action in (session.page or {}).get("actions", []):
        rect = action.get("rect")
        if not rect or action.get("offscreen") or action["kind"] not in {"click", "fill", "select"}:
            continue
        if action["kind"] == "select":  # One tag per dropdown, not one per option.
            if action.get("node") in seen:
                continue
            seen.add(action.get("node"))
        x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
        draw.rectangle([x, y, x + w, y + h], outline=(245, 176, 65), width=2)
        tag = action["id"]
        draw.rectangle([x, max(0, y - 14), x + 8 * len(tag) + 6, max(14, y)], fill=(245, 176, 65))
        draw.text((x + 3, max(0, y - 14)), tag, fill=(0, 0, 0))
    if image.width > width:
        image = image.resize((width, round(image.height * width / image.width)))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=70)
    return base64.b64encode(out.getvalue()).decode()


def choose(session, step, log):
    last = None
    shot = marked_screenshot(session)
    for _ in range(3):
        try:
            output, meta = model.chat_json(PILOT, context_for(session, step, log), model=pilot_model(), max_tokens=4096, role="pilot",
                                           images=[shot] if shot else (),
                                          reasoning_effort=os.environ.get("TEXT_MODEL_EFFORT", "low"))
            return validate(output, session), meta
        except (ValueError, KeyError, TypeError, RuntimeError, json.JSONDecodeError) as error:
            if "TEXT_MODEL_API_KEY" in str(error):
                raise
            last = error
    raise ValueError(f"The pilot gave no valid operation after 3 tries ({last})")
