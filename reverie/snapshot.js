(() => {
  if (!document.body) return null;
  const cache = window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const safe = e => !['password','file','hidden'].includes(e.type);
  const visible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(document.getElementById(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (['INPUT','SELECT'].includes(e.tagName) ? '' : [...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
        n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? name(n,seen) : '').join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  // Legacy table forms leave controls unnamed ("Order ID:" sits in the previous cell; a GO button sits under a
  // section heading). Only when a control has no accessible name, borrow the nearest visible caption.
  const caption = e => {
    const clean = t => (t || '').replace(/\s+/g,' ').replace(/[:*]\s*$/,'').trim().slice(0,80);
    const field = e.matches('select,textarea,input:not([type=button]):not([type=submit]):not([type=image]):not([type=reset])');
    if (e.matches('input[type=radio],input[type=checkbox]')) {
      // Legacy forms put an option's words right after its radio or checkbox, unlinked: "( ) Enter location".
      let text = '';
      for (let n = e.nextSibling; n && text.length < 80; n = n.nextSibling) {
        if (n.nodeType === 1 && n.matches('input,select,textarea,button,br,table,div,p')) break;
        text += ' ' + (n.nodeType === 3 ? n.textContent : n.innerText || '');
      }
      if (clean(text)) return clean(text);
    }
    if (field) {  // A field's caption sits beside it; a button's caption is the section it acts on.
      const cell = e.closest('td,th');
      for (let c = cell?.previousElementSibling; c; c = c.previousElementSibling) {
        const t = clean(c.innerText); if (t) return t;
      }
      for (let p = e.previousElementSibling; p; p = p.previousElementSibling) {
        if (p.matches('input,select,textarea,button')) break;
        const t = clean(p.innerText); if (t) return t;
      }
    }
    // An unnamed submit (icon button) acts on its form: name it after the form's first field.
    if (!field && (e.type === 'submit' || e.type === 'image')) {
      const form = e.form || e.closest('form');
      const first = form && [...form.elements].find(f =>
        f.matches('input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=image]),textarea,select'));
      const what = first && clean(name(first) || first.placeholder || first.name);
      if (what) return 'Submit ' + what;
    }
    // A section title: a heading element, or short text styled bold (legacy "header" rows are styled cells).
    const titled = el => {
      if (el.matches('h1,h2,h3,h4,h5,h6,th,legend,caption,[role="heading"],b,strong')) return true;
      const weight = parseInt(getComputedStyle(el).fontWeight, 10);
      return weight >= 600 && (el.innerText || '').trim().length <= 80;
    };
    let node = e;
    for (let depth = 0; node && depth < 6; depth++, node = node.parentElement) {
      for (let p = node.previousElementSibling; p; p = p.previousElementSibling) {
        // A form row, a control, or a "Label:" caption is not a section title.
        if (p.matches('input,select,textarea,button') || p.querySelector?.('input,select,textarea')) continue;
        const candidates = [p, ...p.querySelectorAll('*')].filter(el => el.children.length === 0 || titled(el));
        const h = candidates.find(el => titled(el) && clean(el.innerText) && !/:\s*$/.test(el.innerText.trim()));
        const t = clean(h?.innerText); if (t) return t;
      }
    }
    return '';
  };
  // Sites sometimes name an input by its value; its description, name, id and placeholder say what it is for.
  const hint = e => {
    if (!['INPUT','TEXTAREA','SELECT'].includes(e.tagName)) return '';
    const described=(e.getAttribute('aria-describedby')||'').split(/\s+/)
      .map(id=>document.getElementById(id)?.textContent||'').join(' ');
    const parts=[described,e.name,e.id,e.placeholder].map(s=>(s||'')
      .replace(/([a-z])([A-Z])/g,'$1 $2').replace(/[-_]+/g,' ').replace(/\s+/g,' ').trim()).filter(Boolean);
    return [...new Set(parts)].join(' · ').slice(0,100);
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'option','gridcell','combobox','textbox','searchbox','spinbutton'];
  // Widget libraries render suggestion rows with no ARIA role (jQuery UI autocomplete, Select2, typeahead).
  const suggestions='.ui-autocomplete .ui-menu-item-wrapper,.ui-autocomplete li.ui-menu-item:not(:has(.ui-menu-item-wrapper)),'+
    '.select2-results__option,.tt-suggestion,.autocomplete-suggestion,.pac-item';
  const selector='a[href],button,input,textarea,select,summary,[contenteditable="true"],'+suggestions+','+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const role = e => {
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.matches(suggestions)) return 'option';
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A') return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (['text','email','url','tel'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    [...document.querySelectorAll('input,textarea,select')].filter(safe)
      .map(e=>[identity(e),e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly])];
  cache.guard=e=>{
    if (!e?.isConnected || !visible(e)) return null;
    // Keep context local to the target. A whole form or dialog may contain live prices, timers, or
    // status text whose unrelated updates must not invalidate an otherwise unchanged control.
    const scope=e.closest('article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e),role(e),name(e),e.value??null,e.checked??null,e.selectedIndex??null,
      e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),scope?.innerText?.slice(0,6000)||''];
  };
  const actions=[];
  for (const e of document.querySelectorAll(selector)) {
    if (!safe(e) || !visible(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
    const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2, rname=role(e);
    if (!rname || r.width<=0 || r.height<=0) continue;
    // Agent-control sessions set __jevFullPage to also list controls outside the viewport. Those carry
    // offscreen:true and are scrolled into view and hit-tested again by the executor before any input.
    const onscreen = x>=0 && y>=0 && x<innerWidth && y<innerHeight;
    if (!onscreen && window.__jevFullPage !== true) continue;
    if (onscreen) {
      const hit=document.elementFromPoint(x,y);
      if (!hit || (hit!==e && !e.contains(hit))) continue;
    }
    if (rname==='gridcell' && e.querySelector('button,[role="button"]')) continue;
    const fallback = caption(e) || hint(e).split(' · ')[0];
    const base={node:identity(e),role:rname,label:name(e)||(fallback ? fallback+' ('+rname+')' : rname),
      rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
    if (!onscreen) base.offscreen=true;
    const purpose=hint(e);
    if (purpose && purpose!==base.label) base.hint=purpose;
    for (const key of ['checked','selected','expanded']) {
      const value=e.getAttribute('aria-'+key);
      if (value!==null) base[key]=value;
    }
    if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
    if (e.tagName==='SELECT') {
      for (const o of e.options) if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        actions.push({...base,kind:'select',value:o.value,
          current_value:[...e.selectedOptions].map(o=>o.label).join(', '),label:base.label+' → '+o.label});
    } else {
      const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(rname) ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      const value='value' in e ? String(e.value) :
        e.isContentEditable || rname==='combobox' ? e.innerText.trim() : '';
      actions.push({...base,kind:editable?'fill':'click',value});
      if (editable) actions.push({...base,kind:'click',value,label:'Open '+base.label});
    }
  }
  // Open pickers sometimes list plain clickable items with no role (a trip-type menu of <li>s).
  // Only inside dialogs, menus and listboxes: whole-page pointer scanning would flood the action list.
  const seen=new Set(actions.map(a=>cache.nodes.get(a.node)));
  const pickers='[role="dialog"],dialog[open],[aria-modal="true"],[role="menu"],[role="listbox"],[popover]';
  for (const root of document.querySelectorAll(pickers)) {
    if (!visible(root)) continue;
    for (const e of root.querySelectorAll('*')) {
      if (seen.has(e) || e.closest(selector) || e.querySelector(selector) || !visible(e)) continue;
      if (getComputedStyle(e).cursor!=='pointer' || getComputedStyle(e.parentElement).cursor==='pointer') continue;
      const text=e.innerText?.trim().replace(/\s+/g,' ');
      const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
      if (!text || text.length>80 || r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight) continue;
      const hit=document.elementFromPoint(x,y);
      if (!hit || (hit!==e && !e.contains(hit))) continue;
      seen.add(e);
      actions.push({node:identity(e),role:'option',label:text,rect:{x:r.x,y:r.y,w:r.width,h:r.height},
        kind:'click',value:''});
    }
  }
  const words=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const range=document.createRange(); let node,length=0;
  const cap = window.__jevFullPage === true ? 16000 : 6000;
  while ((node=walker.nextNode()) && length<cap) {
    const value=node.textContent.trim(), parent=node.parentElement;
    if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
    range.selectNodeContents(node); const r=range.getBoundingClientRect();
    if (r.width>0 && r.height>0 && (window.__jevFullPage === true ||
        (r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth))) {
      words.push(value); length+=value.length;
    }
  }
  const text=words.join('\n').slice(0,cap), height=document.documentElement.scrollHeight;
  const page_key=cache.pageKey(), guards={};
  for (const a of actions) if (!(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
  // Compare meaning and identity. Geometry is always resolved and hit-tested just before input.
  const semantics=actions.map(({rect,offscreen,...action})=>action);
  const marker=[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,semantics,page_key[6]];
  const omitted_actions=Math.max(0,actions.length-250);
  actions.splice(250);
  actions.forEach((a,i)=>a.id='e'+(i+1));
  if (scrollY+innerHeight<height-2) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down',delta:560});
  if (scrollY>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-560});
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  return {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text,
    scroll:{y:scrollY,height},actions,marker,page_key,guards,omitted_actions};
})()
