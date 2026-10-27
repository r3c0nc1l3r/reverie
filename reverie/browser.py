"""Observed actions through Browser Harness; one CDP session, no per-step subprocess."""

import base64
import hashlib
import json
import math
import secrets
import sys
import threading
import time
import unicodedata
from contextlib import contextmanager, nullcontext
from pathlib import Path

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp

from .capture import CapturePrivacyError, capture_masked

SCREENSHOT_TIMEOUT_SECONDS = 8.0
VISUAL_STATE_LIMIT = 32 * 1024 * 1024
VISUAL_STATE_CHUNK = 32 * 1024
VISUAL_STATE_TRANSFER_TIMEOUT = 20.0

# Atomically read visible content and controls, preserving actual DOM node identity.
READ_STATE = Path(__file__).with_name("snapshot.js").read_text()
MARKER = f"(() => {{ const state={READ_STATE}; return state?.marker ?? null; }})()"
# Bind a frame to every DOM node's identity, geometry, paint and interaction state, including
# custom controls outside snapshot's action selector. Ignore only our own shadow overlay.
VISUAL_STATE = """(() => {
  const c=window.__jevFast;
  if (!c || !document.body) return null;
  const identity=e=>{if (!c.ids.has(e)) c.ids.set(e,c.next++); const id=c.ids.get(e); c.nodes.set(id,e); return id};
  const nodes=[...document.querySelectorAll('*')].filter(e=>!e.closest('#laya-agent-overlay')).map(e=>{
    const r=e.getBoundingClientRect(), s=getComputedStyle(e);
    const attrs=[...e.attributes].filter(a=>a.name!=='value').map(a=>[a.name,a.value]).sort((a,b)=>a[0].localeCompare(b[0]));
    const text=[...e.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join('');
    const value=e.matches('input[type=password],input[type=file],input[type=hidden]') ? null : (e.value ?? null);
    return [identity(e),identity(e.parentElement || e),r.x,r.y,r.width,r.height,s.display,s.visibility,
      s.opacity,s.pointerEvents,s.zIndex,s.transform,s.clipPath,attrs,text,value,e.checked ?? null];
  });
  return JSON.stringify([performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,nodes]);
})()"""

class StalePage(ValueError):
    """A decision no longer refers to the observed page."""


def visual_time_remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Visual state transfer timed out. Observe again.")
    return min(5.0, remaining)


@contextmanager
def staged_visual_state(evaluate, state):
    """Transfer a signature in bounded IPC requests for an atomic in-page comparison."""
    if not isinstance(state, str):
        raise ValueError("A fresh screenshot is required. Observe again.")
    data = state.encode("utf-8")
    if len(data) > VISUAL_STATE_LIMIT:
        raise ValueError("Visual state exceeds the 32 MiB limit. Observe again.")
    key = secrets.token_hex(16)
    key_js = json.dumps(key)
    deadline = time.monotonic() + VISUAL_STATE_TRANSFER_TIMEOUT

    def transfer(expression):
        evaluate(expression, _response_timeout=visual_time_remaining(deadline))
        visual_time_remaining(deadline)

    try:
        transfer(f"window.__jevFast.visualStates ??= Object.create(null); window.__jevFast.visualStates[{key_js}]=[]")
        for offset in range(0, len(data), VISUAL_STATE_CHUNK):
            chunk = base64.b64encode(data[offset:offset + VISUAL_STATE_CHUNK]).decode("ascii")
            transfer(f"window.__jevFast.visualStates[{key_js}].push({json.dumps(chunk)})")
        yield key, deadline
    finally:
        try:
            evaluate(f"delete window.__jevFast?.visualStates?.[{key_js}]", _response_timeout=2.0)
        except Exception:
            pass


def visual_state_matches(key):
    """Compare against the exact staged bytes without placing them in an IPC request."""
    return """(() => {
      const chunks=window.__jevFast?.visualStates?.[""" + json.dumps(key) + """];
      if (!chunks) return false;
      const bytes=chunks.map(s=>Uint8Array.from(atob(s), c=>c.charCodeAt(0)));
      const decoder=new TextDecoder();
      const state=bytes.map((b,i)=>decoder.decode(b,{stream:i<bytes.length-1})).join('');
      return """ + VISUAL_STATE + """ === state;
    })()"""


class Browser:
    def __init__(self, url, prepare=None):
        self.last_screenshot = None
        self.secret_values = set()
        self.secret_targets = []
        self.privacy_generation = 0
        self._privacy_lock = threading.Lock()
        self._privacy_pending = 0
        self.screenshot_available = True
        ensure_daemon()
        if prepare:
            prepare()  # Browser-wide settings, such as the download folder, before the first navigation.
        self.target = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
        self.session = cdp("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
        self.configure_session()
        self.call("Page.navigate", url=url)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.evaluate("document.readyState") == "complete":
                break
            time.sleep(0.02)

    def configure_session(self):
        self.call("Emulation.setDeviceMetricsOverride", width=1120, height=780, deviceScaleFactor=1, mobile=False)
        # Keep rAF/menus rendering in an owned background tab, without activating the user's Chrome tab.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)

    def reattach(self):
        """Replace a CDP session poisoned by a compositor timeout without replacing its page."""
        previous = self.session
        self.session = cdp("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
        self.configure_session()
        try:
            cdp("Target.detachFromTarget", sessionId=previous)
        except RuntimeError:
            pass

    def call(self, method, **params):
        return cdp(method, session_id=self.session, **params)

    def evaluate(self, expression, **params):
        response = self.call("Runtime.evaluate", expression=expression, returnByValue=True, **params)
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def secret_matches(self, value):
        """Identify values derived from an answer already registered as sensitive."""
        if not isinstance(value, str) or not value:
            return False
        def normalize(text):
            return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())
        candidate = normalize(value)
        for known in getattr(self, "secret_values", ()):
            if value == known:
                return True
            existing = normalize(known)
            if candidate and existing and (candidate == existing or
                    ((min(len(candidate), len(existing)) >= 3 or (candidate.isdigit() and existing.isdigit())) and
                     (candidate in existing or existing in candidate))):
                return True
        return False

    def privacy_revision(self):
        """Return a stable revision or withhold while registrations are in progress."""
        with self._privacy_lock:
            if self._privacy_pending:
                raise CapturePrivacyError("Secret registration in progress; screenshot withheld.")
            return self.privacy_generation

    def register_secret(self, value=None, node=None, point=None):
        """Remember sensitive values and their target forms for this browser session only."""
        with self._privacy_lock:
            self._privacy_pending += 1
            self.privacy_generation += 1
            self.last_screenshot = None
        try:
            if isinstance(value, str) and value:
                self.secret_values.add(value)
            invalidate = getattr(self, "on_secret_registered", None)
            if invalidate:
                invalidate()
            if type(node) is int or point is not None:
                target = self.evaluate("""(([node,point]) => {
              const e=point ? document.elementFromPoint(point[0],point[1]) : window.__jevFast?.nodes.get(node);
              const c=window.__jevFast;
              if (!e || !c) return null;
              if (!c.ids.has(e)) c.ids.set(e,c.next++);
              const id=c.ids.get(e); c.nodes.set(id,e);
              return {origin:performance.timeOrigin,node:id};
            })""" + "(" + json.dumps([node, point]) + ")")
                if not isinstance(target, dict):
                    raise CapturePrivacyError("Sensitive target could not be tracked; action withheld.")
                if target not in self.secret_targets:
                    self.secret_targets.append(target)
        finally:
            with self._privacy_lock:
                self._privacy_pending -= 1
                self.privacy_generation += 1

    def capture_masked(self, **params):
        try:
            revision = self.privacy_revision()
            image = capture_masked(self.call, self.evaluate, values=getattr(self, "secret_values", ()),
                                   targets=getattr(self, "secret_targets", ()), **params)
            if self.privacy_revision() != revision:
                raise CapturePrivacyError("Privacy registration changed during capture; screenshot withheld.")
            return image
        except Exception:
            self.last_screenshot = None
            raise

    def observe(self, screenshot=True, screenshot_fallback=True):
        revision = self.privacy_revision()
        if getattr(self, "after_input", None):
            action, self.after_input = self.after_input, None
            # This is read-only and happens after execution was logged, even if navigation interrupts it.
            try:
                self.call(
                    "Runtime.evaluate",
                    expression="""(action => new Promise(resolve => {
                      const field=window.__jevFast?.nodes.get(action.node);
                      const autocomplete=action.kind==='fill' && field?.getAttribute('role')==='combobox';
                      let frames=0, stopped=false;
                      const finish=()=>{stopped=true;resolve()};
                      setTimeout(finish,autocomplete ? 200 : 50);
                      const ready=()=>{
                        if (stopped) return;
                        const ids=(field?.getAttribute('aria-controls')||field?.getAttribute('aria-owns')||'')
                          .split(/\\s+/).filter(Boolean);
                        const roots=ids.length ? ids.map(id=>document.getElementById(id)).filter(Boolean) : [document];
                        const options=roots.flatMap(root=>[...root.querySelectorAll('[role="option"]')]);
                        if (++frames>=2 && (!autocomplete || options.some(e=>{
                          const r=e.getBoundingClientRect();
                          return r.width && r.height && r.bottom>0 && r.top<innerHeight &&
                            e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
                        }))) finish();
                        else requestAnimationFrame(ready);
                      };
                      requestAnimationFrame(ready);
                    }))(""" + json.dumps(action) + ")",
                    awaitPromise=True,
                    returnByValue=True,
                )
            except RuntimeError:
                pass
        for attempt in range(10):
            try:
                capture = screenshot and self.screenshot_available
                try:
                    page = browser_operation(
                        {"operation": "observe", "session": self.session, "screenshot": capture,
                         "secret_values": getattr(self, "secret_values", ()),
                         "secret_targets": getattr(self, "secret_targets", ())}
                    )
                except CapturePrivacyError:
                    self.last_screenshot = None
                    if not screenshot_fallback:
                        raise
                    page = browser_operation({"operation": "observe", "session": self.session, "screenshot": False})
                except TimeoutError as error:
                    self.last_screenshot = None
                    if not capture or "Page.captureScreenshot" not in str(error):
                        raise
                    if not screenshot_fallback:
                        raise RuntimeError(
                            "Image capture timed out. Choose DOM or Either to continue without a screenshot."
                        ) from error
                    # The structured page state is sufficient for decisions. A wedged Chromium
                    # compositor must not stop the agent or accumulate more screenshot requests.
                    self.screenshot_available = False
                    self.reattach()
                    page = browser_operation(
                        {"operation": "observe", "session": self.session, "screenshot": False}
                    )
                if page.get("screenshot"):
                    self.last_screenshot = page["screenshot"]
                    page["observation_path"] = "image"
                elif screenshot:
                    page["screenshot"] = self.last_screenshot
                    page["screenshot_stale"] = True
                    page["observation_path"] = "dom"
                else:
                    page["observation_path"] = "dom"
                try:
                    if self.privacy_revision() != revision:
                        raise CapturePrivacyError("Privacy registration changed during observation; screenshot withheld.")
                except CapturePrivacyError:
                    self.last_screenshot = None
                    page.pop("screenshot", None)
                    raise
                return page
            except StalePage:
                if attempt == 9:
                    raise
                time.sleep(0.02)
        raise StalePage("Page did not settle")

    def visual_state(self):
        """Return the code-owned DOM signature associated with a visual frame."""
        return self.evaluate(VISUAL_STATE)

    def observe_point(self, page, x, y, text=None, visual_state=None):
        """Resolve a viewport point to a code-owned node from the current observation."""
        if (isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float))
                or not isinstance(y, (int, float)) or not math.isfinite(x) or not math.isfinite(y)
                or not 0 <= x < page.get("w", 0) or not 0 <= y < page.get("h", 0)):
            raise ValueError("Point must be finite and inside the viewport")
        if self.evaluate(MARKER) != page.get("marker"):
            raise StalePage("Page changed since the screenshot. Observe again.")
        with staged_visual_state(self.evaluate, visual_state) as (state_key, deadline):
            target = self.evaluate("""(([x,y,wantsText]) => {
          if (!(""" + visual_state_matches(state_key) + """)) return null;
          const c=window.__jevFast, hit=document.elementFromPoint(x,y);
          if (!c || !hit || hit.closest('[aria-hidden="true"],[inert],[aria-disabled="true"]')) return null;
          const sensitive=e=>e?.matches('input[type=password],input[type=file],input[type=hidden]');
          const control=hit.closest('input,textarea,select,button,a[href],summary,[contenteditable="true"],'+
            '[role="button"],[role="link"],[role="checkbox"],[role="radio"],[role="switch"],[role="tab"],'+
            '[role="option"],[role="textbox"],[role="searchbox"],[role="combobox"],label');
          const e=control || hit.closest('[onclick]') || hit;
          if (['HTML','BODY','LABEL'].includes(e.tagName) || sensitive(e) || sensitive(hit) ||
              sensitive(e.closest('label')?.control) || e.matches(':disabled') ||
              e.closest('[aria-disabled="true"],[inert],[aria-hidden="true"]') ||
              !e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
          const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
            (e.isContentEditable || e.tagName==='TEXTAREA' ||
             (e.tagName==='INPUT' && ['text','email','url','tel','search','number'].includes(e.type)));
          if (wantsText && !editable) return null;
          if (!wantsText && (e.tagName==='SELECT' || sensitive(e) ||
              (e.tagName==='INPUT' && !['text','email','url','tel','search','number','checkbox','radio',
                'button','submit','reset','image'].includes(e.type)))) return null;
          const identity=el=>{ if (!c.ids.has(el)) c.ids.set(el,c.next++);
            const id=c.ids.get(el); c.nodes.set(id,el); return id; };
          const node=identity(e), hitNode=identity(hit), r=e.getBoundingClientRect();
          const label=(c.name(e) || e.getAttribute('aria-label') || [...(e.labels||[])].map(l=>l.innerText).join(' ') ||
            (e.matches('input[type=submit],input[type=button],input[type=reset]') ? e.value : '') ||
            e.innerText || e.getAttribute('title') || e.getAttribute('placeholder') || e.tagName).trim().slice(0,200);
          return {node, hitNode, guard:c.guard(e), action:{id:'visual_'+node,node,kind:wantsText?'fill':'click',
            role:e.getAttribute('role') || (e.tagName==='INPUT'?e.type:e.tagName.toLowerCase()), label,
            submits:e.matches('button[type=submit],input[type=submit],input[type=image]') ||
              (e.tagName==='BUTTON' && !e.hasAttribute('type') && !!e.form),
            rect:{x:r.x,y:r.y,w:r.width,h:r.height}, point:{x,y,hitNode}}};
        })(""" + json.dumps([x, y, text is not None]) + ")", _response_timeout=visual_time_remaining(deadline))
            visual_time_remaining(deadline)
        if not target or not target.get("guard"):
            raise ValueError("Point does not identify a safe visible target")
        page["guards"][str(target["node"])] = target["guard"]
        target["action"]["point"]["guard"] = target["guard"]
        target["action"]["point"]["state"] = visual_state
        return target["action"]

    def fresh(self, page, action=None):
        if action is not None and action.get("point"):
            if self.evaluate(MARKER) != page.get("marker"):
                return False
            node = action["node"]
            return self.evaluate(f"window.__jevFast?.guard(window.__jevFast.nodes.get({node}))") == action["point"]["guard"]
        if action is not None and action["kind"] in {"click", "select", "hover"}:
            node = action["node"]
            if type(node) is not int:
                return False
            current = self.evaluate(
                "(() => { const c=window.__jevFast; "
                f"return c ? [c.pageKey(),c.guard(c.nodes.get({node}))] : null; }})()"
            )
            expected = page["guards"].get(str(node))
            # Navigation, target identity, and target semantics must remain stable. Ignore unrelated
            # live form/dialog context (prices, timers, hidden inputs); execution resolves geometry
            # and hit-tests the target again immediately before dispatching input.
            return bool(
                current
                and expected
                and current[0][:2] == page["page_key"][:2]
                and current[1][:-1] == expected[:-1]
            )
        return self.evaluate(MARKER) == page["marker"]

    def act(self, action, page, text=None):
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "fill" and self.secret_matches(text):
            if type(action.get("node")) is not int:
                raise CapturePrivacyError("Sensitive target could not be tracked; action withheld.")
            self.register_secret(text, action["node"])
        if action["kind"] == "wait":
            time.sleep(0.5)
        result = browser_operation({"operation": "act", "session": self.session, "action": action, "text": text})
        self.after_input = {"kind": action["kind"], "node": action.get("node")} if action["kind"] != "wait" else None
        return result

    def close(self):
        if self.target:
            cdp("Target.closeTarget", targetId=self.target)
            self.target = None


def fingerprint(state):
    content = {k: state[k] for k in ("url", "text", "actions", "scroll")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def browser_operation(request):
    operation = request["operation"]
    session = request["session"]

    def call(method, **params):
        return cdp(method, session_id=session, **params)

    def evaluate(expression, **params):
        result = call("Runtime.evaluate", expression=expression, returnByValue=True, **params)
        if result.get("exceptionDetails"):
            if operation == "act" and request["action"]["kind"] == "select":
                raise RuntimeError("Dropdown execution was interrupted; inspect before retrying.")
            raise StalePage("Document changed during evaluation")
        return result.get("result", {}).get("value")

    if operation == "act":
        action = request["action"]
        kind = action["kind"]
        if kind == "scroll":
            call("Input.dispatchMouseEvent", type="mouseWheel", x=550, y=650, deltaX=0, deltaY=action["delta"])
        elif kind != "wait":
            if type(action["node"]) is not int:
                raise ValueError("Invalid observed node")
            # Code-owned node IDs refer to actual observed elements, never model-generated selectors.
            point = action.get("point")
            state = point.get("state") if point else None
            # Keep the signature out of the request carrying the observed action.
            wire_action = {**action, "point": {k: v for k, v in point.items() if k != "state"}} if point else action
            with staged_visual_state(evaluate, state) if point else nullcontext((None, None)) as (state_key, deadline):
                state_check = visual_state_matches(state_key) if point else "true"
                target = evaluate("""(action => {
              const e=window.__jevFast?.nodes.get(action.node);
              const protectedControl=control => !!control && (
                control.matches('input[type=password],input[type=file],input[type=hidden],:disabled') ||
                !!control.closest('[aria-disabled="true"],[aria-hidden="true"],[inert]'));
              if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[aria-hidden="true"],[inert]') ||
                  (action.kind==='hover' && (protectedControl(e) || protectedControl(e.closest('label')?.control))) ||
                  !e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
              if (action.kind==='fill' && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
              const r=e.getBoundingClientRect(), x=action.point?.x ?? r.x+r.width/2,
                y=action.point?.y ?? r.y+r.height/2;
              if (action.point && (!(""" + state_check + """) ||
                  JSON.stringify(window.__jevFast.guard(e))!==JSON.stringify(action.point.guard) ||
                  window.__jevFast.nodes.get(action.point.hitNode)!==document.elementFromPoint(x,y) ||
                  e.closest('[aria-hidden="true"]') || e.matches('input[type=password],input[type=file],input[type=hidden]') ||
                  e.closest('label')?.control?.matches('input[type=password],input[type=file],input[type=hidden]'))) return null;
              if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
              const hit=document.elementFromPoint(x,y);
              if (!hit || !e.contains(hit)) return null;
              if (action.kind==='hover' && (
                  hit.closest('input[type=password],input[type=file],input[type=hidden],:disabled,[aria-disabled="true"],[inert],[aria-hidden="true"]') ||
                  protectedControl(hit.closest('label')?.control))) return null;
              if (action.kind==='select') {
                if (e.tagName!=='SELECT') return null;
                let option;
                if (Object.hasOwn(action,'option_index')) {
                  if (!Number.isInteger(action.option_index) || action.option_index<0) return null;
                  option=e.options[action.option_index];
                  if (!option || option.value!==action.value || option.label!==action.option_label) return null;
                } else {
                  const matches=[...e.options].filter(o=>o.value===action.value);
                  if (matches.length!==1) return null;
                  option=matches[0];
                }
                if (option.disabled || option.closest('optgroup[disabled]')) return null;
                e.selectedIndex=option.index;
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
              }
              return {x,y};
            })(""" + json.dumps(wire_action) + ")",
                    **({"_response_timeout": visual_time_remaining(deadline)} if point else {}))
                if point:
                    visual_time_remaining(deadline)
                if target is None:
                    if kind == "select":
                        raise RuntimeError("Dropdown execution was not confirmed; inspect before retrying.")
                    raise StalePage("Target changed or is covered. Observe again.")
                if kind == "hover":
                    call("Input.dispatchMouseEvent", type="mouseMoved", x=target["x"], y=target["y"])
                elif kind != "select":
                    x, y = target["x"], target["y"]
                    if not action.get("point"):
                        call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
                    call(
                        "Input.dispatchMouseEvent",
                        type="mousePressed",
                        x=x,
                        y=y,
                        button="left",
                        buttons=1,
                        clickCount=1,
                    )
                    call(
                        "Input.dispatchMouseEvent",
                        type="mouseReleased",
                        x=x,
                        y=y,
                        button="left",
                        buttons=0,
                        clickCount=1,
                    )
                    if kind == "fill":
                        call(
                            "Input.dispatchKeyEvent",
                            type="keyDown",
                            key="a",
                            code="KeyA",
                            modifiers=4 if sys.platform == "darwin" else 2,
                            commands=["selectAll"],
                        )
                        call(
                            "Input.dispatchKeyEvent",
                            type="keyUp",
                            key="a",
                            code="KeyA",
                            modifiers=4 if sys.platform == "darwin" else 2,
                        )
                        if request["text"] == "":  # An explicit clear: delete the selected contents.
                            backspace = {"key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8}
                            call("Input.dispatchKeyEvent", type="keyDown", commands=["deleteBackward"], **backspace)
                            call("Input.dispatchKeyEvent", type="keyUp", **backspace)
                        else:
                            call("Input.insertText", text=request["text"])
        return {"executed": action["id"]}

    info = evaluate(READ_STATE)
    if info is None:
        raise StalePage("Document is navigating")
    info["fingerprint"] = fingerprint(info)
    if request.get("screenshot", True):
        info["screenshot"] = capture_masked(
            call, evaluate, values=request.get("secret_values", ()), targets=request.get("secret_targets", ()),
            _response_timeout=SCREENSHOT_TIMEOUT_SECONDS,
            format="jpeg",
            quality=72,
        )
    return info
