"""Mercury as a steerable decision engine: the text model picks one observed element, never a selector.

The controller (a person or a coding agent) gives a goal and optional hints. Mercury answers with a JSON
choice that must name an element id from the current observation, or DONE / BLOCKED. Everything it
returns is validated before anything runs; an invalid answer executes nothing.
"""

import json

from .. import model

DECIDE = """You operate a web browser one step at a time for a QA tester.
You receive the goal, optional hints from the tester, recent steps, the visible page text, and the list of
interactive elements actually on the page. Choose exactly ONE next step.

Answer with JSON only:
{"choice": "<an element id from the list, a TAB:<n> from the tabs list, or DONE, BLOCKED, or ADMIN>",
 "text": "<the exact text to type; only when the chosen element has kind fill, else null>",
 "reason": "<one short sentence the tester will hear>",
 "confidence": <0.0-1.0>}

Rules:
- The id must be copied from the elements list. Never invent ids, selectors, URLs, or code.
- Use DONE only when the visible page already shows the goal is complete. Use BLOCKED when the goal cannot
  proceed from this page (missing data, an error page, a login you cannot complete).
- Use ADMIN when the test needs a terminal action that only the orchestrator can run (for example test data is
  already used up, a fixture must be reset, or a record is missing). Say what is needed in "reason".
  Never put a command in your answer.
- Elements marked offscreen are real controls further up or down the page; choose them directly, the
  executor scrolls to them. Prefer them over Scroll actions.
- The tabs list shows every open tab. Choose TAB:<n> to switch when the goal continues in another tab
  (for example a window a link just opened).
- Follow the tester's hints; they override your own preference.
- You may receive the fast local model's (Laya's) top candidates and why you were consulted. Pick one of them
  when it is right; otherwise pick a better element from the list.
- Type only values the goal or hints state. Never guess passwords, codes, or personal data.
- Prefer the most direct element. Scroll only when the target is plausibly below the fold."""


def element_rows(actions, limit=250):
    rows = []
    for action in actions[:limit]:
        row = {k: action[k] for k in ("id", "kind", "role", "label", "value", "hint", "checked", "expanded",
                                      "offscreen") if action.get(k) not in (None, "")}
        rows.append(row)
    return rows


def mercury_choose(goal, page, history, hints=(), candidates=None, escalation=None, plan=None, tabs=None):
    actions = page.get("actions", [])
    context = {
        "goal": goal,
        "goal_plan": plan,
        "consulted_because": escalation,
        "laya_candidates": candidates or [],
        "tabs": tabs or [],
        "recent_browser_dialogs": [h.get("dialogs") for h in history[-3:] if h.get("dialogs")],
        "hints": list(hints)[-6:],
        "url": page.get("url"),
        "title": page.get("title"),
        "recent_steps": [{k: h.get(k) for k in ("kind", "label", "text", "by")} for h in history[-8:]],
        "visible_text": page.get("text", "")[:2500],
        "elements": element_rows(actions),
    }
    from .session import scrub

    context = scrub(context)
    last_error = None
    for _ in range(3):  # A fast model occasionally emits malformed or doubled JSON; ask again, never guess.
        try:
            output, meta = model.chat_json(DECIDE, context)
            return validate(output, actions, len(tabs or [])), meta
        except ValueError as error:
            if "TEXT_MODEL_API_KEY" in str(error):
                raise
            last_error = error
    raise ValueError(f"Mercury gave no valid answer after 3 tries ({last_error}); nothing executed.")


def validate(output, actions, tab_count=0):
    if not isinstance(output, dict):
        raise ValueError("Mercury returned no JSON object; nothing executed.")
    choice = output.get("choice")
    by_id = {a["id"]: a for a in actions}
    tab_ok = isinstance(choice, str) and choice.startswith("TAB:") and choice[4:].isdigit() \
        and int(choice[4:]) < tab_count
    if choice not in by_id and choice not in {"DONE", "BLOCKED", "ADMIN"} and not tab_ok:
        raise ValueError(f"Mercury chose {choice!r}, which is not on the page; nothing executed.")
    text = output.get("text")
    action = by_id.get(choice)
    if action and action["kind"] == "fill":
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError("Mercury chose a text field without a value; nothing executed.")
    else:
        text = None
    try:
        confidence = min(1.0, max(0.0, float(output.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    reason = output.get("reason")
    reason = reason.strip()[:240] if isinstance(reason, str) else ""
    return {"choice": choice, "text": text, "reason": reason, "confidence": confidence}


def describe(proposal):
    return json.dumps({k: proposal.get(k) for k in ("engine", "ref", "label", "text", "confidence", "reason")})
