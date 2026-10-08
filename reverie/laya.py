"""Local decisions with Laya through a runtime-independent backend.

A 421M typed-decision encoder answers narrow questions well: which field sets X, does this value
satisfy Y, which suggestion matches Z. It does not reliably answer "what should a browser do next?".
So each step asks narrow questions and composes them with rules that hold on any site:
fill the values the goal states, pick what a typed query or an opened control offers,
submit, then check the goal's finish condition. Every target is an observed element.
"""

import re
import time
import unicodedata
from urllib.parse import urlparse

from .decision_backend import DEFAULT_LOCAL_DECISION_MODEL, create_backend
from .model import plan_goal, validate_choice

DEFAULT_MODEL = DEFAULT_LOCAL_DECISION_MODEL
FIELD_ROLES = {"combobox", "textbox", "searchbox", "spinbutton", "checkbox", "radio", "switch"}
TOGGLES = {"checkbox", "radio", "switch"}
NEGATIVE = {"no", "off", "false", "unchecked", "disabled", "without", "none"}
SUBMIT_WORDS = {"search", "submit", "find", "go", "apply", "done", "continue", "next", "confirm", "show"}
STOP_WORDS = {"the", "and", "for", "with", "from", "find", "open", "stop", "when", "visib", "page", "are", "this"}
MONTH_DAY = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(?:uary|ruary|ch|il|e|y|ust|t|tember|ober|ember)?"
    r"\s+(\d{1,2})\b|\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
)
YES_NO = {"yes": "the current value satisfies the requirement", "no": "the current value does not satisfy it"}
# Contrasting page kinds separated finished from unfinished pages far better than a yes/no question.
UNFINISHED = {
    "form": "a search form that still has to be submitted",
    "results": "a list of search results, without the requested item opened",
    "other": "some other page",
}

MAX_RESULT_WAITS = 12  # about 2 s of observation while submitted results load
NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

_MODEL = None


def laya():
    """Create and warm one decision backend per process."""
    global _MODEL
    if _MODEL is None:
        _MODEL = create_backend()
    return _MODEL


def fold(text):
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def words(text):
    return {w[:5] for w in fold(text).split() if (len(w) > 2 or w.isdigit()) and w[:5] not in STOP_WORDS}


def month_day(text):
    m = MONTH_DAY.search(fold(text))
    return (m[1] or m[4], int(m[2] or m[3])) if m else None


def observed(page):
    """One entry per DOM node, indexed in the same order as model.action_space (the inspector's indices)."""
    elements, nodes = [], {}
    for action in page["actions"]:
        if action["kind"] not in {"click", "fill", "select"}:
            continue
        e = nodes.get(action["node"])
        if e is None:
            e = nodes[action["node"]] = {
                "node": action["node"],
                "index": str(len(elements) + 1),
                "role": action.get("role", ""),
                "label": action["label"].split(" → ")[0].strip(),
                "value": action.get("current_value", action.get("value", "")) or "",
                "checked": action.get("checked"),
                "expanded": action.get("expanded"),
                "hint": action.get("hint", ""),
                "actions": {},
                "options": [],
            }
            elements.append(e)
        if action["kind"] == "select":
            e["options"].append(action)
        else:
            e["actions"].setdefault(action["kind"], action)
    for e in elements:
        if e["role"] in TOGGLES:
            e["current"] = "checked" if e["checked"] in {"true", True} else "unchecked"
        elif e["value"] or (is_field(e) and e["role"] != "button"):
            e["current"] = e["value"]
        else:
            e["current"] = e["label"]
    return elements


def is_field(e):
    # Buttons that display a count ("1 passenger") act as fields; dated buttons are calendar choices.
    counter = e["role"] == "button" and re.search(r"\d", e["label"]) and not month_day(e["label"])
    return e["role"] in FIELD_ROLES or bool(e["options"]) or bool(counter)


def display(e):
    """The name the planner sees and may copy as a requirement's "what"."""
    return f"{e['label'][:80]} ({e['hint'][:60]})" if e.get("hint") else e["label"][:80]


def plannable(e):
    """Elements a requirement can name: fields, and buttons, which often open pickers for dates or counts."""
    return is_field(e) or e["role"] == "button"


def describe(e):
    text = f"{e['role']} {e['label'][:70]}"
    if e.get("hint"):
        text += f" ({e['hint'][:50]})"
    if is_field(e) and e["current"] != e["label"]:
        text += f" = {e['current'][:40] or '(empty)'}"
    if e["options"]:
        text += " (options: " + ", ".join(option_label(o) for o in e["options"][:6]) + ")"
    return text


def option_label(option):
    return option["label"].split(" → ")[-1]


def cabin_class(text):
    value = fold(text)
    for name in ("premium economy", "business class", "first class", "business", "first", "economy"):
        if name in value:
            return name.replace(" class", "")
    return None


def party_count(text):
    value = fold(text)
    if not any(word in value for word in ("passeng", "adult", "child", "children", "infant")):
        return None
    matches = re.findall(
        r"\b(one|two|three|four|five|six|seven|eight|nine|\d+)\s+"
        r"(?:passengers?|adults?|children|child|infants?)\b",
        value,
    )
    return sum(int(NUMBER_WORDS.get(count, count)) for count in matches) if matches else None


def settled(requirement, e):
    """True or False when plain code can tell; None asks Laya."""
    value = requirement["value"]
    if e["role"] in TOGGLES:
        return (e["current"] == "checked") != bool(set(fold(value).split()) & NEGATIVE)
    current = e["current"]
    if not fold(current):
        return False
    wanted_party, current_party = party_count(value), party_count(current)
    if wanted_party is not None and current_party is not None:
        return wanted_party == current_party
    wanted_class, current_class = cabin_class(value), cabin_class(current)
    if wanted_class and current_class:
        return wanted_class == current_class
    if any(fold(option_label(o)) == fold(value) for o in e["options"]):
        return False  # The requested value is still offered as an unselected option.
    wanted, shown = month_day(value), month_day(current)
    if wanted and shown:
        return wanted == shown
    fv, fc = fold(value), fold(current)
    if fv and (fv in fc or (len(fc) >= 3 and fc in fv)):
        return True
    return None


def summary(text, about, limit=200):
    """The page lines sharing the most words with `about`, in page order. Page chrome comes first on most
    sites, so the opening characters rarely describe the page."""
    lines = [line for line in text.splitlines() if line.strip()]
    target = words(about)
    ranked = sorted(range(len(lines)), key=lambda i: -len(words(lines[i]) & target))
    kept, size = set(), 0
    for i in ranked:
        if size >= limit:
            break
        kept.add(i)
        size += len(lines[i])
    return " | ".join(lines[i] for i in sorted(kept))[: limit * 2]


def location(url):
    """Sites often rewrite the query on every edit; a new host or path means a new page."""
    parsed = urlparse(url)
    return parsed.netloc, parsed.path


def titled(title, name):
    """The page title carries most of the name's words, and they make up most of the title. A search results
    page ("X - Search results - Site") names the item too, but is not its page."""
    wanted, shown = words(name), words(title)
    shared = len(wanted & shown)
    return bool(wanted) and shared >= max(1, round(0.6 * len(wanted))) and shared >= 0.6 * len(shown)


def relevance(e, text):
    shared = words(f"{e['label']} {e.get('hint', '')} {e['current']}") & words(text)
    # A semantic match ("adult") must outrank an incidental numeral ("aged 2"). Dates receive
    # their own exact-match bonus below, while numeric-only requirements still retain a weak signal.
    s = sum(2 if not word.isdigit() else 0.25 for word in shared)
    date = month_day(text)
    return s + 5 if date and month_day(e["label"]) == date else s


def preserve_party_details(goal, plan):
    """Keep adult/child distinctions that a text planner may flatten to a passenger total."""
    matches = re.findall(
        r"\b(one|two|three|four|five|six|seven|eight|nine|\d+)\s+"
        r"(adults?|children|child|infants?)\b",
        fold(goal),
    )
    if not matches:
        return
    party = []
    for count, kind in matches:
        count = NUMBER_WORDS.get(count, count)
        noun = "children" if kind in {"child", "children"} and count != "1" else kind
        party.append(f"{count} {noun}")
    for requirement in plan["requirements"]:
        name = fold(requirement["what"])
        if any(word in name for word in ("passeng", "travel", "adult", "child", "infant")):
            requirement["value"] = " and ".join(party)


def shortlist(candidates, text, limit, bonus=None, top_tier=False, margin=1):
    """Keep the likeliest candidates, in document order, so options fit Laya's 256-token question budget.
    With top_tier, only candidates scoring within `margin` points of the best remain."""
    scores = {e["node"]: relevance(e, text) + (bonus(e) if bonus else 0) for e in candidates}
    if top_tier and candidates:
        best = max(scores.values())
        candidates = [e for e in candidates if scores[e["node"]] >= best - margin]
    kept = {e["node"] for e in sorted(candidates, key=lambda e: -scores[e["node"]])[:limit]}
    return [e for e in candidates if e["node"] in kept]


class LayaPolicy:
    def __init__(self, goal):
        self.goal = goal
        self.plan = None
        self.plan_meta = None
        self.fields = {}  # requirement index -> observed node
        self.met = set()
        self.skipped = set()
        self.attempts = {}
        self.pending = None  # the latest decision, until history shows it executed
        self.last = None  # the latest executed step
        self.edit_url = None
        self.submitted = False
        self.waits = 0
        self.seen = 0
        self.tried = {}  # label -> times clicked as the next step
        self.typed = False  # text entered since the last submit
        self.acted = None
        self.search_added = False
        self.frozen = set()  # requirements submitted to an earlier page
        self.failed = {}  # node -> decisions on it that could not execute

    # Bookkeeping ---------------------------------------------------------------------------------------------

    def sync(self, history):
        step = self.pending
        if step and step["node"] is not None and len(history) == self.seen:
            # The decision never ran: the target was covered or the page changed first.
            self.failed[step["node"]] = self.failed.get(step["node"], 0) + 1
        if len(history) > self.seen and step and history[-1].get("choice") == step["choice"]:
            executed = history[-1]
            self.last = step
            if step["req"] is not None:
                self.attempts[step["req"]] = self.attempts.get(step["req"], 0) + 1
                self.edit_url, self.submitted = step["url"], False
                requirement = self.plan["requirements"][step["req"]]
                selected_words = words(step.get("label") or "") & words(requirement["value"])
                semantic_match = any(not word.isdigit() for word in selected_words)
                wanted_date = month_day(requirement["value"])
                exact_date = bool(wanted_date) and month_day(step.get("label") or "") == wanted_date
                filled_value = step["kind"] == "fill" and fold(executed.get("text") or "") == fold(
                    requirement["value"]
                )
                if executed.get("page_changed") and (
                    filled_value or (step["kind"] == "pick" and (semantic_match or exact_date))
                ):
                    self.met.add(step["req"])
                    if step["kind"] == "pick":
                        self.frozen.add(step["req"])
            if step["kind"] == "fill":
                self.typed = True
            if step["kind"] in {"submit", "item"}:
                self.submitted = True
            if step["kind"] == "confirm" and step["req"] is not None:
                self.met.add(step["req"])
                self.frozen.add(step["req"])
            if step["kind"] in {"submit", "item", "next"}:
                self.tried[step["label"]] = self.tried.get(step["label"], 0) + 1
            self.waits = self.waits + 1 if step["kind"] == "wait" else 0
            if step["kind"] != "wait":
                self.acted = step["kind"]  # the latest non-wait step
        self.seen, self.pending = len(history), None

    def ask(self, state, questions):
        result = laya().system_one(state, questions)
        for key, answer in result["answers"].items():
            if questions[key]["type"] == "choice":
                try:
                    validate_choice(answer, questions[key]["criteria"])
                except ValueError:
                    raise ValueError("Invalid Laya response; no action executed.") from None
        self.answers.update(result["answers"])
        self.questions.update(questions)
        self.tokens += result["usage"]["input_tokens"]
        return result["answers"]

    def pick(self, qid, candidates, state, instructions, text, limit=20, bonus=None, allow_none=False,
             top_tier=False, margin=1):
        date = month_day(text)
        dated = [e for e in candidates if date and month_day(e["label"]) == date]
        if len(dated) == 1:
            return dated[0], None  # An exact calendar match needs no model call; Laya confused adjacent days.
        ranked = shortlist(candidates, text, limit, bonus, top_tier, margin)
        if not ranked:
            return None
        if len(ranked) == 1 and not allow_none:
            return ranked[0], None
        criteria = {str(e["node"]): describe(e) for e in ranked}
        if allow_none:
            criteria["none"] = "none of these"
        answer = self.ask(state, {qid: {"type": "choice", "instructions": instructions, "criteria": criteria}})[qid]
        if answer["choice"] == "none":
            return None
        return next(e for e in ranked if str(e["node"]) == answer["choice"]), answer

    # Decisions ----------------------------------------------------------------------------------------------

    def choose(self, page, history):
        started = time.perf_counter()
        self.sync(history)
        if self.edit_url and location(page["url"]) != location(self.edit_url):
            # The form was submitted to a new page. Its values were used; a new page's empty copy of the
            # form (a site-wide search box, say) does not undo them.
            self.typed = False
            self.frozen |= self.met
        elements = observed(page)
        if self.plan is None:
            labels = list(dict.fromkeys(display(e) for e in elements if plannable(e)))
            self.plan, self.plan_meta = plan_goal(self.goal, labels)
            preserve_party_details(self.goal, self.plan)
        self.answers, self.questions, self.tokens = {}, {}, 0
        op, element, action, picked, kind, req, text = self.decide(page, elements)
        answer = picked[1] if picked else None
        indices = {str(e["node"]): e["index"] for e in elements}
        choice = action["id"] if action else {"DONE": "DONE", "BLOCKED": "BLOCKED"}.get(op, "wait")
        probability = answer["probabilities"][answer["choice"]] if answer else 1.0
        target = element["index"] if element else None
        if action and action["kind"] == "select":
            target = f"{element['index']}:{element['options'].index(action) + 1}"
        self.pending = {
            "choice": choice, "kind": kind, "req": req, "node": element["node"] if element else None,
            "url": page["url"], "before": {e["node"] for e in elements},
            "label": element["label"] if element else None,
        }
        return {
            "choice": choice,
            "operation": op,
            "target": target,
            "text": text,
            "action_node": action.get("node") if action else None,
            "action_kind": action.get("kind") if action else None,
            "action_value": action.get("value") if action else None,
            "action_label": action.get("label") if action else None,
            "confidence": answer["confidence"] if answer else 1.0,
            "probabilities": {choice: probability},
            "operation_probabilities": {op: probability},
            "target_probabilities": {
                indices.get(k, k): p for k, p in (answer or {}).get("probabilities", {}).items() if k in indices
            },
            "target_confidence": answer["confidence"] if answer and element else None,
            "raw_answers": self.answers,
            "model": laya().model_name,
            "usage": {"input_tokens": self.tokens, "output_tokens": 0},
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "request": {"plan": self.plan, "questions": self.questions},
        }

    def decide(self, page, elements):
        """Return (operation, element, action, (element, answer) or None, step kind, requirement, text)."""
        reqs = self.plan["requirements"]
        by_node = {e["node"]: e for e in elements}
        clickable = [e for e in elements if "click" in e["actions"] and self.failed.get(e["node"], 0) < 2]
        last = self.last

        # 1. A typed query or an opened control offers new choices: take the one its requirement asks for.
        if last and last["kind"] in {"fill", "open"} and last["req"] is not None:
            r = reqs[last["req"]]
            new = [e for e in clickable if e["node"] not in last["before"]]
            # Suggestions name the value; controls that appear beside them ("Clear", "Swap") do not.
            requested = words(r["value"])
            semantic = [
                e
                for e in new
                if any(
                    not word.isdigit()
                    for word in words(f"{e['label']} {e.get('hint', '')} {e['current']}") & requested
                )
            ]
            new = semantic or [e for e in new if relevance(e, r["value"])]
            state = f"Requirement: {r['what']} = {r['value']}"
            picked = self.pick("option", new, state, f"Which option sets {r['what']} to {r['value']}?",
                               r["value"], allow_none=True)
            if picked:
                return self.click(picked, "pick", last["req"])

        # Some pickers (calendars, passenger counts) stay open after a value changes and expose an explicit
        # confirmation button. Autocomplete lists do not, so a leading confirmation verb avoids the form's
        # separate Search button while accepting descriptive labels such as "Done. Search for one-way flights".
        if last and last["kind"] == "pick":
            confirmations = [
                e
                for e in clickable
                if fold(e["label"]).split()[:1] and fold(e["label"]).split()[0] in {"done", "apply", "confirm"}
            ]
            if len(confirmations) == 1:
                return self.click((confirmations[0], None), "confirm", last["req"])

        # An item to open that nothing on the page names has to be searched for first.
        item = self.plan.get("open")
        if item and not self.search_added and not titled(page["title"], item):
            search = [e for e in elements if "fill" in e["actions"] and
                      (e["role"] == "searchbox" or "searc" in words(e["label"]))]
            if search and not any(relevance(e, item) for e in clickable):
                reqs.append({"what": "search", "value": item})
                self.search_added = True

        # 2. Requirements in the goal's order: map each to an observed element, then check its value.
        if reqs and not any(plannable(e) for e in elements):
            # Nothing to fill yet: the page is still loading or showing an interstitial. This costs no attempt.
            return "WAIT", None, None, None, "wait", None, None
        self.refresh(page, elements, by_node)
        for i, r in enumerate(reqs):
            if i in self.met or i in self.skipped:
                continue
            if self.attempts.get(i, 0) >= 3:
                self.skipped.add(i)
                continue
            e = by_node.get(self.fields.get(i))
            state = f"Requirement: {r['what']} = {r['value']}"
            if e is None:
                # A control about this requirement that already displays its value ("Travellers and cabin
                # class: 1 Adult, Economy") settles it. Both the name and the value must appear.
                # Calendar days name a date too, but they are choices, not displays.
                shown = [c for c in elements if plannable(c) and c["role"] not in TOGGLES and not month_day(c["label"])
                         and words(c["label"]) & words(r["what"]) and words(c["label"]) & words(r["value"])
                         and settled(r, {**c, "current": c["label"], "options": []})]
                if shown:
                    self.met.add(i)
                    continue
                about = f"{r['what']} {r['value']}"
                options = [c for c in clickable if c["role"] not in TOGGLES or words(c["label"]) & words(about)]
                options = [c for c in options if relevance(c, about)] or options
                picked = self.pick(f"set_{i}", options, state, f"Which element sets {r['what']} to {r['value']}?",
                                   about, allow_none=True)
                if not picked:
                    # Often the page is mid-render. Wait (one attempt); the attempt limit skips it for good.
                    return "WAIT", None, None, None, "wait", i, None
                # It may open a picker (a trip-type menu, a calendar); step 1 then chooses from what appears.
                return self.click(picked, "open", i)
            if "fill" in e["actions"]:
                return "TYPE_TEXT", e, e["actions"]["fill"], None, "fill", i, r["value"]
            if e["options"]:
                exact = [o for o in e["options"] if fold(option_label(o)) == fold(r["value"])]
                similar = [o for o in e["options"] if words(option_label(o)) & words(r["value"])]
                if exact or len(similar) == 1:
                    return "SELECT", e, (exact or similar)[0], None, "select", i, None
                answer = self.ask(state, {f"select_{i}": {
                    "type": "choice",
                    "instructions": f"Which option sets {r['what']} to {r['value']}?",
                    "criteria": {str(n): option_label(o) for n, o in enumerate(e["options"])},
                }})[f"select_{i}"]
                option = e["options"][int(answer["choice"])]
                return "SELECT", e, option, (e, answer), "select", i, None
            return "CLICK", e, e["actions"]["click"], None, "toggle" if e["role"] in TOGGLES else "open", i, None

        # 3. Everything stated is set. Check the finish condition once something was submitted or navigated.
        finish = self.plan["finish"]
        navigated = self.edit_url is not None and location(page["url"]) != location(self.edit_url)
        if item:
            # An opened item names its page. Accept its title when it carries the item's words, or the words
            # of the element Laya chose to open it.
            chosen = (last and last["kind"] == "item" and relevance({"label": last["label"], "current": ""}, item)
                      and titled(page["title"], last["label"]))
            if chosen or titled(page["title"], item):
                return "DONE", None, None, None, "done", None, None
        elif self.submitted or navigated or not reqs:
            # Laya's yes/no finish check was unreliable; contrasting page kinds separated real outcomes.
            state = f"Page title: {page['title']}\nPage: {summary(page['text'], finish)}"
            done = self.ask(state, {"done": {
                "type": "choice", "instructions": "Which best describes the current page?",
                "criteria": {"finish": finish, **UNFINISHED},
            }})["done"]
            # A submit that led to a new page while every stated value still holds is a search outcome:
            # accept it once Laya sees results, and wait while they load.
            searched = self.acted == "submit" and navigated and self.met >= set(range(len(reqs)))
            # Laya rarely labels a real results page as one, so also count results that name the requested
            # values: two or more elements mentioning at least three of them (route, date, ...).
            wanted = set().union(*(words(r["value"]) for r in reqs)) if reqs else set()
            matching = [e for e in clickable if len(words(e["label"]) & wanted) >= min(3, len(wanted))]
            # Laya called a loading results skeleton "finish", so with stated values it needs rows naming them,
            # or its verdict after the full wait for results.
            laya_done = done["choice"] in {"finish", "results"}
            if (not reqs and done["choice"] == "finish") or (
                searched and (len(matching) >= 2 or (laya_done and self.waits >= MAX_RESULT_WAITS))
            ):
                return "DONE", None, None, None, "done", None, None
            if searched and self.waits < MAX_RESULT_WAITS:
                return "WAIT", None, None, None, "wait", None, None
        if last and last["kind"] in {"submit", "item", "next"} and self.waits < 2 and (self.submitted or navigated):
            return "WAIT", None, None, None, "wait", None, None
        mapped = {self.fields.get(i) for i in range(len(reqs))}
        fresh = {e["node"] for e in clickable if last and e["node"] not in last["before"]}
        # A next-step target clicked twice already has shown it does not advance the goal.
        candidates = [e for e in clickable if e["node"] not in mapped and self.tried.get(e["label"], 0) < 2]

        def submits(e):
            return 2 * bool(set(fold(e["label"]).split()) & SUBMIT_WORDS) + (e["node"] in fresh)

        state = f"Goal: {self.goal}\nFinish condition: {finish}\nPage title: {page['title']}\nPage: {page['text']}"
        if self.typed:
            # Typed search text is not applied until its form is submitted, so submit before opening results.
            buttons = [e for e in candidates if e["role"] == "button"]
            picked = self.pick("submit", buttons, state, "Which button submits the filled form?", "",
                               bonus=submits, top_tier=True)
            if picked:
                return self.click(picked, "submit", None)
        if item:
            named = [e for e in candidates if relevance(e, item) and not is_field(e)]
            # Near-duplicates ("completeness" vs "incompleteness") fooled Laya, so only the elements naming
            # the most of the item's words stay; Laya breaks exact ties.
            picked = self.pick("item", named, state, f"Which element opens {item}?", item, top_tier=True, margin=0)
            if picked:
                return self.click(picked, "item", None)
        # Otherwise click what the goal names: the elements sharing the most words with it; Laya breaks ties.
        picked = self.pick("next", candidates, state, "Which element should be clicked next to reach the goal?",
                           f"{self.goal} {finish}", bonus=lambda e: e["node"] in fresh, top_tier=True, margin=0)
        if not picked:
            return "BLOCKED", None, None, None, "blocked", None, None
        return self.click(picked, "next", None)

    def click(self, picked, kind, req):
        e = picked[0]
        return "CLICK", e, e["actions"]["click"], picked, kind, req, None

    def assign(self, todo, free):
        """Match requirements to fields. Laya is asked both ways (which field sets this requirement, which
        requirement does this field hold); the product matched Flights fields better than either direction.
        The most confident pairs are assigned first, so two requirements never share one field.
        There is no "none" option: in tests it outvoted the right field. Requirements no field can hold
        reach the attempt limit instead. Laya shares one state per request, so each question is one call."""
        reqs = self.plan["requirements"]
        free = shortlist(free, " ".join(f"{reqs[i]['what']} {reqs[i]['value']}" for i in todo), 20)
        fields = {str(e["node"]): describe(e) for e in free}
        options = {str(i): f"{reqs[i]['what']} = {reqs[i]['value']}" for i in todo}
        if len(fields) == 1:
            only = next(iter(fields))
            by_requirement = {i: {only: 1.0} for i in todo}
        else:
            by_requirement = {
                i: self.ask(f"Requirement: {options[str(i)]}", {f"field_{i}": {
                    "type": "choice",
                    "instructions": "Which element shows or sets this requirement?",
                    "criteria": fields,
                }})[f"field_{i}"]["probabilities"]
                for i in todo
            }
        by_field = {
            node: self.ask(f"Form field: {text}", {f"holds_{node}": {
                "type": "choice", "instructions": "Which requirement does this form field hold?",
                "criteria": {**options, "none": "none of these"},
            }})[f"holds_{node}"]["probabilities"]
            for node, text in fields.items()
        }
        # A shared word between the field's label and the requirement's name ("Departure", "departure date")
        # doubles the pair's score.
        label = {str(e["node"]): words(e["label"]) for e in free}
        pairs = sorted(
            (
                (by_requirement[i][node] * by_field[node][str(i)] * (1 + bool(label[node] & words(reqs[i]["what"]))),
                 i, node)
                for i in todo for node in fields
            ),
            reverse=True,
        )
        done, used = set(), set()
        for _p, i, node in pairs:
            if i not in done and node not in used:
                self.fields[i] = int(node)
                done.add(i)
                used.add(node)

    def refresh(self, page, elements, by_node):
        """Map unmapped requirements to observed elements, then check their current values."""
        reqs = self.plan["requirements"]
        open_reqs = [i for i in range(len(reqs)) if i not in self.skipped and i not in self.frozen]
        fields = [e for e in elements if is_field(e)]
        # One field holds one requirement. Fields kept by other requirements are not offered again.
        taken = {self.fields.get(i) for i in open_reqs if self.fields.get(i) in by_node}
        todo = []
        for i in open_reqs:
            if i in self.met or self.fields.get(i) in by_node:
                continue
            r = reqs[i]
            free = [e for e in fields if e["node"] not in taken]
            # A dropdown offering exactly the requested value needs no model call.
            exact = [e for e in free if any(fold(option_label(o)) == fold(r["value"]) for o in e["options"])]
            # The planner names requirements by the observed field label when one sets them.
            requirement_name = fold(r["what"])
            named = [
                e
                for e in elements
                if plannable(e)
                and e["node"] not in taken
                and requirement_name
                and (
                    requirement_name in fold(e["label"])
                    or requirement_name in fold(display(e))
                )
            ]
            if len(exact) == 1 or len(named) == 1:
                self.fields[i] = (exact or named)[0]["node"]
                taken.add(self.fields[i])
            else:
                todo.append(i)
        free = [e for e in fields if e["node"] not in taken]
        if todo and free:
            self.assign(todo, free)
        for i in todo:
            # A checkbox is named by what it sets; one sharing no words with the requirement cannot hold it.
            e = by_node.get(self.fields.get(i))
            r = reqs[i]
            if e and e["role"] in TOGGLES and not words(e["label"]) & words(f"{r['what']} {r['value']}"):
                del self.fields[i]
        checks = {}
        for i in open_reqs:
            e = by_node.get(self.fields.get(i))
            if e is None:
                continue
            verdict = settled(reqs[i], e)
            if verdict is None and i not in self.met:
                checks[i] = e
            elif verdict:
                self.met.add(i)
            else:
                self.met.discard(i)
        for i, e in checks.items():
            r = reqs[i]
            answer = self.ask(f"Requirement: {r['what']} = {r['value']}\nCurrent value: {e['current']}", {
                f"met_{i}": {"type": "choice", "instructions": "Does the current value satisfy the requirement?",
                             "criteria": YES_NO},
            })[f"met_{i}"]
            if answer["choice"] == "yes":
                self.met.add(i)
