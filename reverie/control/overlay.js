(payload => {
  // Lives outside <body> and under aria-hidden, so snapshot.js never reads it as page text or actions.
  // Caption and highlight ignore pointer events, so hit-testing of real targets is unchanged.
  const doc = document.documentElement;
  if (!doc) return null;
  let root = document.getElementById('laya-agent-overlay');
  if (!root) {
    root = document.createElement('div');
    root.id = 'laya-agent-overlay';
    root.setAttribute('aria-hidden', 'true');
    root.attachShadow({mode: 'open'}).innerHTML = `
      <style>
        :host { all: initial; }
        .box { position: fixed; inset: auto 16px 16px 16px; z-index: 2147483647; pointer-events: none;
          font: 15px/1.4 system-ui, sans-serif; display: flex; flex-direction: column; gap: 8px; align-items: center; }
        .caption { max-width: 900px; background: rgba(17,24,39,.92); color: #f9fafb; padding: 10px 16px;
          border-radius: 10px; box-shadow: 0 6px 24px rgba(0,0,0,.35); display: flex; gap: 10px; align-items: baseline; }
        .caption[hidden] { display: none; }
        .tag { font-weight: 700; color: #fbbf24; white-space: nowrap; }
        .status { font-size: 12px; color: #9ca3af; white-space: nowrap; }
        .prompt { pointer-events: auto; background: #fff; color: #111827; border: 2px solid #f59e0b; border-radius: 12px;
          padding: 14px 16px; width: min(640px, 92vw); box-shadow: 0 10px 40px rgba(0,0,0,.4); }
        .prompt[hidden] { display: none; }
        .question { font-weight: 600; margin-bottom: 10px; white-space: pre-wrap; }
        .row { display: flex; gap: 8px; flex-wrap: wrap; }
        textarea { width: 100%; box-sizing: border-box; min-height: 56px; font: inherit; margin-bottom: 10px;
          border: 1px solid #d1d5db; border-radius: 8px; padding: 8px; }
        button { font: inherit; border: 0; border-radius: 8px; padding: 8px 14px; background: #111827; color: #fff; cursor: pointer; }
        button.secondary { background: #e5e7eb; color: #111827; }
        .hl { position: fixed; z-index: 2147483646; pointer-events: none; border: 3px solid #f59e0b;
          border-radius: 6px; box-shadow: 0 0 0 4px rgba(245,158,11,.25); transition: all .15s ease; }
        .hl[hidden] { display: none; }
      </style>
      <div class="hl" hidden></div>
      <div class="box">
        <div class="prompt" hidden>
          <div class="question"></div>
          <textarea placeholder="Type a reply (optional)"></textarea>
          <div class="row"></div>
        </div>
        <div class="caption" hidden><span class="tag">Agent</span><span class="text"></span><span class="status"></span></div>
      </div>`;
    doc.appendChild(root);
  }
  const shadow = root.shadowRoot;
  const caption = shadow.querySelector('.caption');
  const hl = shadow.querySelector('.hl');
  const prompt = shadow.querySelector('.prompt');
  if (payload.caption !== undefined) {
    caption.hidden = !payload.caption;
    shadow.querySelector('.text').textContent = payload.caption || '';
    shadow.querySelector('.status').textContent = payload.status || '';
  }
  if (payload.highlight !== undefined) {
    const r = payload.highlight;
    hl.hidden = !r;
    if (r) Object.assign(hl.style, {left: (r.x - 4) + 'px', top: (r.y - 4) + 'px',
      width: (r.w + 8) + 'px', height: (r.h + 8) + 'px'});
  }
  if (payload.prompt !== undefined) {
    const p = payload.prompt;
    if (!p) {
      prompt.hidden = true;
      prompt.dataset.id = '';
    } else if (prompt.dataset.id !== p.id) {
      prompt.dataset.id = p.id;
      window.__layaAgentReply = null;
      shadow.querySelector('.question').textContent = p.question;
      const text = shadow.querySelector('textarea');
      text.value = '';
      text.hidden = !p.allow_text;
      const row = shadow.querySelector('.row');
      row.replaceChildren();
      (p.choices && p.choices.length ? p.choices : ['Continue']).forEach((choice, i) => {
        const button = document.createElement('button');
        button.textContent = choice;
        if (i) button.className = 'secondary';
        button.addEventListener('click', () => {
          window.__layaAgentReply = {id: p.id, choice, text: text.value};
        });
        row.appendChild(button);
      });
      prompt.hidden = false;
      if (p.allow_text) text.focus();
    }
  }
  return window.__layaAgentReply || null;
})
