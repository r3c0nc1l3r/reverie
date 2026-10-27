"""Capture screenshots with opaque masks before image data leaves the capture boundary."""

import base64
import io
import json
import logging
import math
import os

from PIL import Image, ImageDraw


class CapturePrivacyError(RuntimeError):
    """A screenshot could not be safely masked."""


def secret_selectors():
    """Read trusted selectors; ignore invalid entries without exposing them in logs."""
    try:
        value = json.loads(os.environ.get("REVERIE_SECRET_SELECTORS", "[]"))
        if not isinstance(value, list):
            raise ValueError
    except (ValueError, TypeError):
        logging.warning("Screenshot masking: invalid selector configuration ignored.")
        return []
    result = [s for s in value if isinstance(s, str) and s.strip()]
    if len(result) != len(value):
        logging.warning("Screenshot masking: invalid selector entries ignored.")
    return result


# This reads geometry only. Values and selector strings are never returned in the metadata.
MASK_GEOMETRY = r"""(([selectors, values, targets]) => {
  const rects = [], documents = [], vw = innerWidth, vh = innerHeight;
  let invalidSelector=false, fieldError=false, nonfieldSelector=false;
  selectors=selectors.filter(s=>{ try { document.querySelector(s); return true; }
    catch (_) { invalidSelector=true; return false; } });
  const norm=s=>String(s || "").normalize('NFKC');
  if (!vw || !vh) throw Error('viewport');
  const intersect = (a,b) => [Math.max(a[0],b[0]),Math.max(a[1],b[1]),
    Math.min(a[2],b[2]),Math.min(a[3],b[3])];
  const add = (r, clip, interior=false) => { const q=intersect(r,clip);
    if(q[2]>q[0] && q[3]>q[1]) rects.push([...q,interior]); };
  const rootClip=[0,0,vw,vh];
  const targetElements=targets.map(t=>{
    try {
    if (t.origin!==performance.timeOrigin) return null;
    const original=Number.isInteger(t.node) ? window.__jevFast?.nodes.get(t.node) : null;
    if (original?.isConnected) {
      const r=original.getBoundingClientRect();
      if (!r.width || !r.height || !original.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
      return [original];
    }
    return null;
    } catch (_) { fieldError=true; return null; }
  });
  function walk(root, ox, oy, sx, sy, clip, doc) {
    if (root === doc) documents.push([doc.defaultView.performance.timeOrigin, doc.defaultView.scrollX,
      doc.defaultView.scrollY, doc.defaultView.innerWidth, doc.defaultView.innerHeight]);
    for (const e of root.querySelectorAll('*')) {
      try {
      const r=e.getBoundingClientRect();
      const box=[ox+r.left*sx,oy+r.top*sy,ox+r.right*sx,oy+r.bottom*sy];
      const labelled=(e.getAttribute('aria-labelledby') || '').split(/\s+/).map(id=>
        root.getElementById(id)?.textContent || '').join(' ');
      const attrs=[e.name,e.id,e.getAttribute('aria-label'),labelled,
        e.getAttribute('placeholder'),...[...(e.labels || [])].map(l=>l.textContent)].join(' ').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ');
      const numeric=(e.getAttribute('inputmode') || '').toLowerCase()==='numeric' || e.type==='number';
      const code=!/\b(?:postal|postcode|zip|case|status)\b/i.test(attrs) &&
        /\b(?:code|otp|totp|token|passcode|pin)\b/i.test(attrs);
      const auto=(e.getAttribute('autocomplete') || '').toLowerCase().split(/\s+/).includes('one-time-code');
      const selected=selectors.some(s=>e.matches(s));
      const editable=e.tagName==='INPUT' ? ['text','password','email','url','tel','search','number'].includes(e.type) : e.matches('textarea,[contenteditable=true],[role=textbox]');
      if (selected && !editable) nonfieldSelector=true;
      const matched=selected && editable;
      const value=typeof e.value==='string' ? e.value : (e.isContentEditable ? e.textContent : '');
      const nv=norm(value);
      const known=editable && !!value && values.some(v=>value===v || norm(v)===nv);
      const target=editable && targetElements.some(matches=>matches && matches.includes(e));
      if (editable && (e.matches('input[type="password"]') || auto || (numeric && code) || matched || known || target)) {
        // Only native text controls have a trustworthy empty value. A selector may name
        // an image, a custom widget, or another region with sensitive painted content.
        const textControl=e.tagName==='TEXTAREA' || (e.tagName==='INPUT' &&
          ['text','password','search','email','tel','url','number'].includes(e.type));
        const style=doc.defaultView.getComputedStyle(e);
        const imagePaint=style.backgroundImage!=='none' || style.borderImageSource!=='none';
        const trulyEmpty=textControl && value.length===0 && !(e.validity && e.validity.badInput);
        // Explicitly selected image paint may itself contain private data.
        if (!trulyEmpty || (matched && imagePaint)) {
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
            // Uncertain paint gets a local margin, never the viewport.
            add(box,clip);
          }
        }
      }
      if (e.shadowRoot) walk(e.shadowRoot,ox,oy,sx,sy,clip,doc);
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
          if (!child || !child.documentElement || transformed || !e.clientWidth || !e.clientHeight)
            { fieldError=true; continue; }
          const fx=r.width/e.offsetWidth, fy=r.height/e.offsetHeight;
          if (!Number.isFinite(fx) || !Number.isFinite(fy)) { continue; }
          walk(child,ox+(r.left+e.clientLeft*fx)*sx,oy+(r.top+e.clientTop*fy)*sy,
            sx*fx,sy*fy,frameClip,child);
        } catch (_) { fieldError=true; }
      }
      } catch (_) { fieldError=true; }
    }
  }
  walk(document,0,0,1,1,rootClip,document);
  return {width:vw,height:vh,rects,documents,invalidSelector,fieldError,nonfieldSelector};
})"""


def closed_shadow_rects(call, selectors, values):
    """Find local field rectangles in closed roots where CDP can inspect them."""
    rects = []
    unsupported_in_frame = False
    root = call("DOM.getDocument", depth=-1, pierce=True)["root"]
    def walk(node, closed=False, in_frame=False):
        nonlocal unsupported_in_frame
        closed = closed or node.get("shadowRootType") == "closed"
        if closed and in_frame:
            unsupported_in_frame = True
        name = node.get("nodeName", "").lower()
        # Frame coordinates require additional transforms; leave these unsupported.
        attrs = dict(zip(node.get("attributes", [])[::2], node.get("attributes", [])[1::2]))
        editable = name in ("input", "textarea") or attrs.get("contenteditable") == "true" or attrs.get("role") == "textbox"
        if closed and not in_frame and (editable or (selectors and not name.startswith("#"))):
            try:
                obj = call("DOM.resolveNode", backendNodeId=node["backendNodeId"])["object"]
                oid = obj.get("objectId")
                if oid:
                    result = call("Runtime.callFunctionOn", objectId=oid, returnByValue=True,
                        arguments=[{"value": selectors}, {"value": list(values)}],
                        functionDeclaration=r"""function(selectors,values) {
                          if (!(this instanceof Element)) return null;
                          const e=this, root=e.getRootNode();
                          const labelled=(e.getAttribute('aria-labelledby') || '').split(/\s+/).map(id=>
                            root.getElementById(id)?.textContent || '').join(' ');
                          const a=[e.name,e.id,e.getAttribute('aria-label'),labelled,e.getAttribute('placeholder'),
                            ...[...(e.labels || [])].map(l=>l.textContent)].join(' ').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ');
                          const numeric=(e.getAttribute('inputmode') || '').toLowerCase()==='numeric' || e.type==='number';
                          const code=!/\b(?:postal|postcode|zip|case|status)\b/i.test(a) && /\b(?:code|otp|totp|token|passcode|pin)\b/i.test(a);
                          const auto=(e.getAttribute('autocomplete') || '').toLowerCase().split(/\s+/).includes('one-time-code');
                          const selected=selectors.some(s=>{try{return e.matches(s)}catch(_){return false}});
                          const editable=e.tagName==='INPUT' ? ['text','password','email','url','tel','search','number'].includes(e.type) : e.matches('textarea,[contenteditable=true],[role=textbox]');
                          if (selected && !editable) return {nonfield:true};
                          const matched=selected && editable;
                          const value=typeof e.value==='string' ? e.value : (e.isContentEditable ? e.textContent : '');
                          const known=editable && !!value && values.some(v=>value===v || value.normalize('NFKC')===v.normalize('NFKC'));
                          if (!editable || !(e.matches('input[type=password]') || auto || (numeric && code) || matched || known)) return null;
                          const native=e.tagName==='TEXTAREA' || (e.tagName==='INPUT' && ['text','password','search','email','tel','url','number'].includes(e.type));
                          const style=getComputedStyle(e);
                          if (native && !value && !(e.validity && e.validity.badInput) && !(matched && (style.backgroundImage!=='none' || style.borderImageSource!=='none'))) return null;
                          const r=e.getBoundingClientRect();
                          const borders=['borderLeftWidth','borderTopWidth','borderRightWidth','borderBottomWidth'].map(k=>parseFloat(style[k]));
                          const colors=['borderLeftColor','borderTopColor','borderRightColor','borderBottomColor'].map(k=>style[k]);
                          const styles=['borderLeftStyle','borderTopStyle','borderRightStyle','borderBottomStyle'].map(k=>style[k]);
                          let safe=true, ancestor=e;
                          while (ancestor) {
                            const a=getComputedStyle(ancestor);
                            if (a.transform!=='none' || a.translate!=='none' || a.rotate!=='none' || a.scale!=='none' || a.perspective!=='none' || a.zoom!=='1' || a.filter!=='none' || a.backdropFilter!=='none') safe=false;
                            ancestor=ancestor.parentElement || ancestor.getRootNode()?.host || null;
                          }
                          const safeBorder=style.backgroundImage==='none' && style.borderImageSource==='none' &&
                            borders.every((n,i)=>Number.isFinite(n) && n>=0 && (n===0 || (styles[i]==='solid' && /^rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)$/.test(colors[i]))));
                          const textSafe=native && style.textShadow==='none' && style.overflowX!=='visible' && style.overflowY!=='visible' && parseFloat(style.overflowClipMargin)===0;
                          if (safe && safeBorder && textSafe && r.width>borders[0]+borders[2] && r.height>borders[1]+borders[3])
                            return [r.left+borders[0],r.top+borders[1],r.right-borders[2],r.bottom-borders[3],true];
                          return [r.left,r.top,r.right,r.bottom,true];
                        }""")
                    rect = result.get("result", {}).get("value")
                    if isinstance(rect, list):
                        rects.append(rect)
                    elif isinstance(rect, dict) and rect.get("nonfield"):
                        logging.warning("Screenshot masking: selector matched a non-field and was ignored.")
                    call("Runtime.releaseObject", objectId=oid)
            except Exception:
                logging.warning("Screenshot masking: a closed-root field could not be inspected.")
        for child in node.get("children", []):
            walk(child, closed, in_frame)
        for shadow in node.get("shadowRoots", []):
            walk(shadow, closed, in_frame)
        if node.get("contentDocument"):
            walk(node["contentDocument"], closed, True)
    walk(root)
    if unsupported_in_frame:
        logging.warning("Screenshot masking: closed-root fields inside a frame cannot be inspected.")
    return rects


def capture_masked(call, evaluate, *, values=(), targets=(), **params):
    """Capture fresh pixels and best-effort mask local sensitive field geometry."""
    selectors = secret_selectors()
    expression = MASK_GEOMETRY + "(" + json.dumps([selectors, list(values), list(targets)]) + ")"

    def geometry():
        try:
            result = evaluate(expression)
            if not isinstance(result, dict):
                raise ValueError
            if result.get("invalidSelector"):
                logging.warning("Screenshot masking: invalid selector ignored.")
            try:
                result["rects"].extend(closed_shadow_rects(call, selectors, values))
            except Exception:
                logging.warning("Screenshot masking: closed-root discovery unavailable.")
            if result.get("nonfieldSelector"):
                logging.warning("Screenshot masking: selector matched a non-field and was ignored.")
            if result.get("fieldError"):
                logging.warning("Screenshot masking: some fields could not be inspected.")
            return result
        except Exception:
            logging.warning("Screenshot masking: field geometry unavailable.")
            return None

    before = geometry()
    # Capture raw PNG before painting so compression cannot spread sensitive pixels.
    capture_params = {**params, "format": "png"}
    capture_params.pop("quality", None)
    data = call("Page.captureScreenshot", **capture_params)["data"]
    after = geometry()
    try:
        with Image.open(io.BytesIO(base64.b64decode(data, validate=True))) as source:
            image = source.convert("RGB")
        width, height = image.size
        draw = ImageDraw.Draw(image)
        for sample in (before, after):
            if not sample:
                continue
            try:
                vw, vh = sample["width"], sample["height"]
                if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (vw, vh)):
                    raise ValueError
                for rect in sample["rects"]:
                    try:
                        if (len(rect) != 5 or not isinstance(rect[4], bool) or
                                not all(isinstance(v, (int, float)) and math.isfinite(v) for v in rect[:4])):
                            raise ValueError
                        x1, y1, x2, y2 = rect[:4]
                        pad = 0 if rect[4] else 12
                        bounds = (max(0, math.floor(x1 * width / vw) - pad),
                                  max(0, math.floor(y1 * height / vh) - pad),
                                  min(width - 1, math.ceil(x2 * width / vw) + pad),
                                  min(height - 1, math.ceil(y2 * height / vh) + pad))
                        x1, y1, x2, y2 = bounds
                        if x1 > x2 or y1 > y2:
                            continue
                        draw.rectangle(bounds, fill=(29, 36, 48))
                        for x in range(x1 - (y2 - y1), x2 + 1, 12):
                            start, end = max(0, x1 - x), min(y2 - y1, x2 - x)
                            if start <= end:
                                draw.line((x + start, y1 + start, x + end, y1 + end), fill=(89, 102, 119))
                    except Exception:
                        logging.warning("Screenshot masking: a field could not be painted.")
            except Exception:
                logging.warning("Screenshot masking: invalid field geometry ignored.")
        output = io.BytesIO()
        try:
            image.save(output, format="PNG" if params.get("format") == "png" else "JPEG", quality=95)
        except Exception:
            logging.warning("Screenshot masking: output conversion failed; returning PNG.")
            output = io.BytesIO()
            image.save(output, format="PNG")
        return base64.b64encode(output.getvalue()).decode("ascii")
    except Exception:
        logging.warning("Screenshot masking: image processing failed; returning the captured image.")
        if params.get("format") != "png":
            try:
                with Image.open(io.BytesIO(base64.b64decode(data, validate=True))) as source:
                    output = io.BytesIO()
                    source.convert("RGB").save(output, format="JPEG", quality=95)
                return base64.b64encode(output.getvalue()).decode("ascii")
            except Exception:
                pass
        return data
