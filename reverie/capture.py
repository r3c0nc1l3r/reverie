"""Capture screenshots with opaque masks before image data leaves the capture boundary."""

import base64
import io
import json
import math
import os
import secrets

from PIL import Image, ImageDraw


class CapturePrivacyError(RuntimeError):
    """A screenshot could not be safely masked."""


def secret_selectors():
    """Read trusted operator selectors; invalid configuration prevents image capture."""
    try:
        value = json.loads(os.environ.get("REVERIE_SECRET_SELECTORS", "[]"))
        if not isinstance(value, list) or any(not isinstance(s, str) or not s.strip() for s in value):
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise CapturePrivacyError("Invalid REVERIE_SECRET_SELECTORS configuration; screenshot withheld.") from None


# This reads geometry only. Values and selector strings are never returned in the metadata.
MASK_GEOMETRY = r"""(([selectors, values, targets]) => {
  const rects = [], documents = [], vw = innerWidth, vh = innerHeight;
  const norm=s=>String(s || "").normalize('NFKC').toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
  if (!vw || !vh) throw Error('viewport');
  const intersect = (a,b) => [Math.max(a[0],b[0]),Math.max(a[1],b[1]),
    Math.min(a[2],b[2]),Math.min(a[3],b[3])];
  const add = (r, clip) => { const q=intersect(r,clip); if(q[2]>q[0] && q[3]>q[1]) rects.push(q); };
  const rootClip=[0,0,vw,vh];
  const targetElements=targets.map(t=>{
    if (t.origin!==performance.timeOrigin) return null;
    const original=Number.isInteger(t.node) ? window.__jevFast?.nodes.get(t.node) : null;
    if (original?.isConnected) {
      const r=original.getBoundingClientRect();
      if (!r.width || !r.height || !original.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
      return [original];
    }
    return null;
  });
  function filtered(e, doc) {
    for (let ancestor=e; ancestor; ancestor=ancestor.parentElement || ancestor.getRootNode()?.host || null)
      if (doc.defaultView.getComputedStyle(ancestor).filter !== 'none') return true;
    return false;
  }
  function walk(root, ox, oy, sx, sy, clip, doc, inheritedFilter=false) {
    if (root === doc) documents.push([doc.defaultView.performance.timeOrigin, doc.defaultView.scrollX,
      doc.defaultView.scrollY, doc.defaultView.innerWidth, doc.defaultView.innerHeight]);
    for (const selector of selectors) root.querySelector(selector); // Validate even if nothing matches.
    for (const e of root.querySelectorAll('*')) {
      const r=e.getBoundingClientRect();
      const box=[ox+r.left*sx,oy+r.top*sy,ox+r.right*sx,oy+r.bottom*sy];
      const labelled=(e.getAttribute('aria-labelledby') || '').split(/\s+/).map(id=>
        doc.getElementById(id)?.textContent || '').join(' ');
      const attrs=[e.name,e.id,e.getAttribute('aria-label'),labelled,
        e.getAttribute('placeholder'),...[...(e.labels || [])].map(l=>l.textContent)].join(' ');
      const numeric=(e.getAttribute('inputmode') || '').toLowerCase()==='numeric' || e.matches('input[type="number"]');
      const code=/(?:code|otp|totp|token)/i.test(attrs);
      const auto=(e.getAttribute('autocomplete') || '').toLowerCase().split(/\s+/).includes('one-time-code');
      const matched=selectors.some(s=>e.matches(s));
      const value=typeof e.value==='string' ? e.value : (e.isContentEditable ? e.textContent : '');
      const nv=norm(value);
      const known=value && values.some(v=>{
        if (value===v) return true;
        const n=norm(v); return n && nv &&
          (n===nv || ((Math.min(n.length,nv.length)>=3 || (/^\p{N}+$/u.test(n) && /^\p{N}+$/u.test(nv))) &&
            (n.includes(nv) || nv.includes(n))));
      });
      const editable=e.matches('input,textarea,[contenteditable="true"],[role="textbox"]');
      // If an identity is gone or ambiguous, do not assume the replacement remains in its old form.
      const target=editable && targetElements.some(matches=>!matches || matches.includes(e));
      if (e.matches('input[type="password"]') || auto || (numeric && code) || matched || known || target) {
        const style=doc.defaultView.getComputedStyle(e);
        if (inheritedFilter || filtered(e,doc)) add(rootClip,rootClip);
        else if (style.textShadow!=='none' ||
            (!e.matches('input,textarea') && (style.overflowX==='visible' || style.overflowY==='visible')))
          add(clip,clip);
        else add(box,clip);
      }
      if (e.shadowRoot) walk(e.shadowRoot,ox,oy,sx,sy,clip,doc,inheritedFilter);
      if (e.tagName==='IFRAME' || e.tagName==='FRAME') {
        const frameClip=intersect(box,clip);
        try {
          const child=e.contentDocument;
          let ancestor=e, transformed=false;
          while (ancestor) {
            const style=doc.defaultView.getComputedStyle(ancestor);
            if (style.transform!=='none' || style.perspective!=='none' || style.zoom!=='1') transformed=true;
            ancestor=ancestor.parentElement || ancestor.getRootNode()?.host || null;
          }
          const frameFiltered=inheritedFilter || filtered(e,doc);
          if (!child || !child.documentElement || transformed || !e.clientWidth || !e.clientHeight)
            { if (frameFiltered) add(rootClip,rootClip); else add(box,clip); continue; }
          const fx=r.width/e.offsetWidth, fy=r.height/e.offsetHeight;
          if (!Number.isFinite(fx) || !Number.isFinite(fy)) {
            if (frameFiltered) add(rootClip,rootClip); else add(box,clip); continue;
          }
          walk(child,ox+(r.left+e.clientLeft*fx)*sx,oy+(r.top+e.clientTop*fy)*sy,
            sx*fx,sy*fy,frameClip,child,frameFiltered);
        } catch (_) { if (inheritedFilter || filtered(e,doc)) add(rootClip,rootClip); else add(box,clip); }
      }
    }
  }
  walk(document,0,0,1,1,rootClip,document);
  return {width:vw,height:vh,rects,documents};
})"""


# Observers report transient DOM edits even if their geometry is restored before the second read.
WATCH_START = r"""(key => {
  const observers=[], cleanups=[], roots=[]; let dirty=false;
  function watch(root) {
    roots.push(root);
    if (root.getAnimations && root.getAnimations({subtree:true}).some(a=>a.playState==='running' || a.pending))
      throw Error('animation');
    const observer=new MutationObserver(()=>{dirty=true});
    observer.observe(root,{subtree:true,childList:true,attributes:true,characterData:true});
    observers.push(observer);
    if (root.nodeType===9) {
      const mark=()=>{dirty=true};
      for (const event of ['scroll','input','change','animationstart','transitionrun']) {
        root.addEventListener(event,mark,true); cleanups.push(()=>root.removeEventListener(event,mark,true));
      }
    }
    for (const e of root.querySelectorAll('*')) {
      if (e.shadowRoot) watch(e.shadowRoot);
      if (e.tagName==='IFRAME' || e.tagName==='FRAME') {
        let child=null; try { child=e.contentDocument; } catch (_) { /* frame is covered */ }
        if (child) watch(child);
      }
    }
  }
  try { watch(document); }
  catch (_) { for (const o of observers) o.disconnect(); for (const f of cleanups) f(); throw Error('watch'); }
  window[key]=()=>{
    if (roots.some(r=>r.getAnimations && r.getAnimations({subtree:true}).some(a=>a.playState==='running' || a.pending)))
      dirty=true;
    for (const o of observers) { if (o.takeRecords().length) dirty=true; o.disconnect(); }
    for (const f of cleanups) f();
    delete window[key]; return !dirty;
  };
  return true;
})"""


def closed_shadow_masks(call):
    """Inspect the pierced CDP tree and cover hosts of closed shadow roots."""
    root = call("DOM.getDocument", depth=-1, pierce=True)["root"]
    hosts = []

    def walk(node, in_frame=False):
        shadows = node.get("shadowRoots", [])
        if any(shadow.get("shadowRootType") == "closed" for shadow in shadows):
            hosts.append(node["backendNodeId"])
        for child in node.get("children", []):
            walk(child, in_frame)
        for shadow in shadows:
            walk(shadow, in_frame)
        if node.get("contentDocument"):
            walk(node["contentDocument"], True)

    walk(root)
    # A closed root may paint beyond a tiny or display:contents host.
    return hosts



def capture_masked(call, evaluate, *, values=(), targets=(), **params):
    """Return only a sanitized CDP screenshot; withhold it if geometry changes or masking fails."""
    watch_key = None
    try:
        selectors = secret_selectors()
        expression = MASK_GEOMETRY + "(" + json.dumps([selectors, list(values), list(targets)]) + ")"
        watch_key = "__reverieCapture_" + secrets.token_hex(16)
        if evaluate(WATCH_START + "(" + json.dumps(watch_key) + ")") is not True:
            raise ValueError
        before = evaluate(expression)
        shadow_before = closed_shadow_masks(call)
        if not isinstance(before, dict):
            raise ValueError
        data = call("Page.captureScreenshot", **params)["data"]
        after = evaluate(expression)
        shadow_after = closed_shadow_masks(call)
        clean = evaluate("(() => { const f=window[" + json.dumps(watch_key) + "]; return f ? f() : false; })()")
        watch_key = None
        if before != after or shadow_before != shadow_after or clean is not True:
            raise ValueError
        with Image.open(io.BytesIO(base64.b64decode(data, validate=True))) as source:
            image = source.convert("RGB")
        width, height = image.size
        vw, vh = before["width"], before["height"]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (vw, vh, width, height)):
            raise ValueError
        draw = ImageDraw.Draw(image)
        if shadow_before:
            draw.rectangle((0, 0, width, height), fill="black")
        for rect in before["rects"]:
            if len(rect) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in rect):
                raise ValueError
            x1, y1, x2, y2 = rect
            draw.rectangle((math.floor(x1 * width / vw) - 12, math.floor(y1 * height / vh) - 12,
                            math.ceil(x2 * width / vw) + 12, math.ceil(y2 * height / vh) + 12), fill="black")
        output = io.BytesIO()
        image.save(output, format="PNG" if params.get("format") == "png" else "JPEG", quality=95)
        return base64.b64encode(output.getvalue()).decode("ascii")
    except (CapturePrivacyError, TimeoutError):
        raise
    except Exception:
        raise CapturePrivacyError("Screenshot privacy check failed; screenshot withheld.") from None
    finally:
        if watch_key:
            try:
                evaluate("(() => { const f=window[" + json.dumps(watch_key) + "]; if (f) f(); })()")
            except Exception:
                pass
