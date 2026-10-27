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
  const add = (r, clip, interior=false) => { const q=intersect(r,clip);
    if(q[2]>q[0] && q[3]>q[1]) rects.push([...q,interior]); };
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
        // Only native text controls have a trustworthy empty value. A selector may name
        // an image, a custom widget, or another region with sensitive painted content.
        const textControl=e.tagName==='TEXTAREA' || (e.tagName==='INPUT' &&
          ['text','password','search','email','tel','url','number'].includes(e.type));
        const style=doc.defaultView.getComputedStyle(e);
        const imagePaint=style.backgroundImage!=='none' || style.borderImageSource!=='none';
        const trulyEmpty=textControl && value.length===0 && !(e.validity && e.validity.badInput);
        // Explicitly selected image paint may itself contain private data.
        if (inheritedFilter || filtered(e,doc)) {
          add(rootClip,rootClip);
        } else if (!trulyEmpty || (matched && imagePaint)) {
          let ancestor=e, safe=true;
          while (ancestor) {
            const a=doc.defaultView.getComputedStyle(ancestor);
            if (a.transform!=='none' || a.translate!=='none' || a.rotate!=='none' || a.scale!=='none' ||
                a.perspective!=='none' || a.zoom!=='1' || a.filter!=='none' || a.backdropFilter!=='none') safe=false;
            ancestor=ancestor.parentElement || ancestor.getRootNode()?.host || null;
          }
          if (style.borderImageSource!=='none' &&
              !style.borderImageOutset.split(/\s+/).every(v=>parseFloat(v)===0)) safe=false;
          const clipped=['hidden','clip'].includes(style.overflowX) &&
            ['hidden','clip'].includes(style.overflowY) && parseFloat(style.overflowClipMargin)===0;
          const boundedImage=e.tagName==='IMG' && style.boxShadow==='none';
          let contained=(clipped || boundedImage) && !e.shadowRoot &&
            style.boxShadow==='none' && style.outlineStyle==='none';
          if (contained && !boundedImage) {
            for (const child of e.querySelectorAll('*')) {
              const cs=doc.defaultView.getComputedStyle(child);
              // Positioned descendants whose containing block is outside this region may escape its clip.
              if (child.shadowRoot || cs.position==='fixed' ||
                  (cs.position==='absolute' && (!child.offsetParent || !e.contains(child.offsetParent)))) {
                contained=false; break;
              }
            }
          }
          const borders=['borderLeftWidth','borderTopWidth','borderRightWidth','borderBottomWidth']
            .map(k=>parseFloat(style[k]));
          const colors=['borderLeftColor','borderTopColor','borderRightColor','borderBottomColor']
            .map(k=>style[k]);
          const borderStyles=['borderLeftStyle','borderTopStyle','borderRightStyle','borderBottomStyle']
            .map(k=>style[k]);
          // Only opaque ordinary borders with no image paint can safely remain visible.
          const safeBorder=!imagePaint && borders.every((n,i)=>Number.isFinite(n) && n>=0 &&
            (n===0 || (borderStyles[i]==='solid' &&
              /^rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)$/.test(colors[i]))));
          const textSafe=textControl && style.textShadow==='none' &&
            style.overflowX!=='visible' && style.overflowY!=='visible' &&
            parseFloat(style.overflowClipMargin)===0;
          if (safe && textSafe && safeBorder &&
              r.width>borders[0]+borders[2] && r.height>borders[1]+borders[3]) {
            add([ox+(r.left+borders[0])*sx,oy+(r.top+borders[1])*sy,
              ox+(r.right-borders[2])*sx,oy+(r.bottom-borders[3])*sy],clip,true);
          } else if (safe && (textSafe || contained)) {
            // Include all border and background paint, with no oversized cover of neighbors.
            add(box,clip,true);
          } else {
            // Unknown paint or transformed controls can extend beyond their box.
            add(clip,clip);
          }
        }
      }
      if (e.shadowRoot) walk(e.shadowRoot,ox,oy,sx,sy,clip,doc,inheritedFilter);
      if (e.tagName==='IFRAME' || e.tagName==='FRAME') {
        const frameClip=intersect(box,clip);
        try {
          const child=e.contentDocument;
          let ancestor=e, transformed=false;
          while (ancestor) {
            const style=doc.defaultView.getComputedStyle(ancestor);
            if (style.transform!=='none' || style.translate!=='none' || style.rotate!=='none' ||
                style.scale!=='none' || style.perspective!=='none' || style.zoom!=='1') transformed=true;
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
        # JPEG compression before masking can spread secret pixels outside the mask.
        capture_params = {**params, "format": "png"}
        capture_params.pop("quality", None)  # CDP accepts quality only for JPEG/WebP.
        data = call("Page.captureScreenshot", **capture_params)["data"]
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

        def paint_mask(bounds):
            x1, y1, x2, y2 = bounds
            draw.rectangle(bounds, fill=(29, 36, 48))
            # Fixed, opaque stripes identify privacy masking without encoding field content.
            for x in range(x1 - (y2 - y1), x2 + 1, 12):
                start = max(0, x1 - x)
                end = min(y2 - y1, x2 - x)
                if start <= end:
                    draw.line((x + start, y1 + start, x + end, y1 + end), fill=(89, 102, 119))

        if shadow_before:
            paint_mask((0, 0, width - 1, height - 1))
        for rect in before["rects"]:
            if (len(rect) != 5 or not isinstance(rect[4], bool) or
                    not all(isinstance(v, (int, float)) and math.isfinite(v) for v in rect[:4])):
                raise ValueError
            x1, y1, x2, y2 = rect[:4]
            pad = 0 if rect[4] else 12
            bounds = (max(0, math.floor(x1 * width / vw) - pad), max(0, math.floor(y1 * height / vh) - pad),
                      min(width - 1, math.ceil(x2 * width / vw) + pad),
                      min(height - 1, math.ceil(y2 * height / vh) + pad))
            if bounds[0] <= bounds[2] and bounds[1] <= bounds[3]:
                paint_mask(bounds)
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
