// PokeBench social review. Renders each draft as the post it is about to become, then
// walks a manual copy/paste publish. Nothing here holds a credential and nothing posts:
// the dashboard's whole job is to get the right text onto the clipboard and the right
// page onto the screen, in that order.
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const URL_RE = /https?:\/\/[^\s<]+/g;

let state = {drafts: [], platforms: {}, view: 'pending', platform: 'all', q: ''};

// ---------- counting ----------
// X bills every link at 23 characters regardless of its real length (t.co), so a draft
// that looks 40 over can be comfortably under. Bluesky counts GRAPHEMES, not UTF-16 code
// units, so an emoji is 1 and "e" + combining accent is 1.
const graphemes = text => {
  if (typeof Intl === 'undefined' || !Intl.Segmenter) return [...text].length;
  return [...new Intl.Segmenter('en', {granularity: 'grapheme'}).segment(text)].length;
};
function count(text, platform) {
  const cfg = state.platforms[platform] || {};
  if (platform === 'x') return text.replace(URL_RE, 'x'.repeat(cfg.url_weight || 23)).length;
  if (cfg.unit === 'graphemes') return graphemes(text);
  return text.length;
}

const firstUrl = text => (String(text).match(URL_RE) || [])[0] || '';
const domainOf = url => { try { return new URL(url).hostname.replace(/^www\./, '').toUpperCase(); } catch { return ''; } };
// The preview shows the body as the platform will: the trailing bare link becomes a card,
// so showing it twice would misrepresent the post.
const bodyWithoutTrailingUrl = text => String(text).replace(/\s*https?:\/\/[^\s<]+\s*$/, '').trimEnd();
const mediaUrl = path => '/api/media?path=' + encodeURIComponent(path);
// The platform fetches a link card's title and image from the URL itself at post time.
// We cannot know either here, so the preview says so rather than inventing a headline.
const cardNote = 'link preview built by the platform';

function linkify(text) {
  return esc(text).replace(/https?:\/\/[^\s&<]+/g, m => `<span class="ln">${m}</span>`);
}

// ---------- platform previews ----------
// Each renderer imitates one platform closely enough to judge the post by eye. They are
// mockups, not embeds: no platform script runs here and nothing is fetched from them.
const previews = {
  x(d) {
    const url = d.link || firstUrl(d.body);
    const text = bodyWithoutTrailingUrl(d.body);
    return `<div class="pv pv-x">
      <div class="av">PB</div>
      <div class="col">
        <div class="who"><span class="nm">PokéBench</span><span class="hd">@pokebenchtv</span><span class="ts">· now</span></div>
        <div class="body">${linkify(text)}</div>
        ${url ? `<div class="card">${mediaBlock(d, '16/9')}<div class="cap"><div class="dm">${esc(domainOf(url))}</div><div class="dm">${esc(cardNote)}</div></div></div>` : mediaBlock(d, '16/9')}
        <div class="acts"><span>💬 0</span><span>🔁 0</span><span>♡ 0</span><span>📊 0</span></div>
      </div></div>`;
  },
  bluesky(d) {
    const url = d.link || firstUrl(d.body);
    const text = bodyWithoutTrailingUrl(d.body);
    return `<div class="pv pv-bluesky">
      <div class="av">PB</div>
      <div class="col">
        <div class="who"><span class="nm">PokéBench</span><span class="hd">@pokebench.tv</span><span class="ts">· now</span></div>
        <div class="body">${linkify(text)}</div>
        ${url ? `<div class="card">${mediaBlock(d, '1.91/1')}<div class="cap"><div class="dm">${esc(cardNote)}</div><div class="dm">${esc(domainOf(url))}</div></div></div>` : mediaBlock(d, '1.91/1')}
        <div class="acts"><span>💬 0</span><span>🔁 0</span><span>♡ 0</span></div>
      </div></div>`;
  },
  reddit(d) {
    return `<div class="pv pv-reddit">
      <div class="votes"><span>▲</span><span>1</span><span>▼</span></div>
      <div class="col">
        <div class="who"><span class="sub">r/${esc(d.subreddit || 'LocalLLaMA')}</span><span>· Posted by u/VibeCodyH</span><span>· now</span></div>
        <div class="title">${esc(d.title || '(no title)')}</div>
        <div class="body">${linkify(d.body)}</div>
        ${mediaBlock(d, '16/9')}
        <div class="acts"><span>💬 0 Comments</span><span>Share</span><span>Save</span></div>
      </div></div>`;
  },
  discord(d) {
    // Discord renders **bold** inline; the embed is what a link unfurls into.
    const md = t => linkify(t).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    const url = d.link || firstUrl(d.body);
    return `<div class="pv pv-discord">
      <div class="av">PB</div>
      <div class="col">
        <div class="who"><span class="nm">PokéBench</span><span class="bot">BOT</span><span class="ts">Today at ${new Date().toLocaleTimeString([], {hour:'numeric', minute:'2-digit'})}</span></div>
        <div class="body">${md(bodyWithoutTrailingUrl(d.body))}</div>
        ${url ? `<div class="embed"><div class="et">${esc(domainOf(url))}</div><div class="ed">${esc(cardNote)}</div></div>` : ''}
        ${mediaBlock(d, '16/9')}
      </div></div>`;
  },
  instagram(d) {
    return `<div class="pv pv-instagram">
      <div class="hd2"><div class="av">PB</div><span class="nm">pokebenchtv</span></div>
      <div class="sq">${d.media && d.media[0] ? `<img src="${esc(mediaUrl(d.media[0]))}" alt="">` : 'no image attached — 1:1 required'}</div>
      <div class="acts"><span>♡</span><span>💬</span><span>✈</span></div>
      <div class="body"><b>pokebenchtv</b>${linkify(d.body)}</div>
    </div>`;
  },
  tiktok(d) {
    return `<div class="pv pv-tiktok">
      <div class="poster">${d.media && d.media[0] ? `<img src="${esc(mediaUrl(d.media[0]))}" alt="">` : 'no clip attached — 9:16'}</div>
      <div class="rail"><div class="av">PB</div><span><i>♡</i>0</span><span><i>💬</i>0</span><span><i>↗</i>0</span></div>
      <div class="cap"><div class="nm">@pokebenchtv</div><div class="body">${esc(d.body)}</div></div>
    </div>`;
  },
};

function mediaBlock(d, ratio) {
  if (!d.media || !d.media.length) return '';
  const file = d.media[0];
  return /\.(png|jpe?g|gif|webp)$/i.test(file)
    ? `<img class="shot" style="aspect-ratio:${ratio}; object-fit:cover" src="${esc(mediaUrl(file))}" alt="">`
    : `<div class="shot" style="aspect-ratio:${ratio}; display:flex; align-items:center; justify-content:center; color:#8a8a8a; font-size:12px">${esc(file.split('/').pop())}</div>`;
}

// ---------- cards ----------
const STATE_LABEL = {pending: 'Needs review', approved: 'Approved', sent_back: 'Sent back', posted: 'Posted'};

function card(d) {
  const cfg = state.platforms[d.platform] || {label: d.platform, limit: 0};
  const used = count(d.body, d.platform);
  const over = cfg.limit && used > cfg.limit;
  const render = previews[d.platform];
  const canPost = d.status === 'approved';
  return `<article class="draft ${d.status === 'posted' ? 'is-posted' : ''}" data-id="${esc(d.id)}">
    <div class="draft-top">
      <div class="left">
        <span class="plat" style="background:${esc(cfg.chip || '#E8E6DE')}">${esc(cfg.label || d.platform)}</span>
        <span class="kind">${esc(d.kind || '')}</span>
      </div>
      <span class="state ${esc(d.status)}">${esc(STATE_LABEL[d.status] || d.status)}</span>
    </div>
    <div class="preview-wrap">${render ? render(d) : `<pre>${esc(d.body)}</pre>`}</div>
    <div class="meta">
      <span class="${over ? 'over' : ''}">${used}${cfg.limit ? ' / ' + cfg.limit : ''} ${cfg.unit === 'graphemes' ? 'graphemes' : 'chars'}${over ? ' — too long' : ''}</span>
      <span>${d.media && d.media.length ? d.media.length + ' file' + (d.media.length > 1 ? 's' : '') : 'No media'}</span>
    </div>
    ${d.note ? `<div class="note"><b>SENT BACK</b>${esc(d.note)}</div>` : ''}
    ${d.posted_url ? `<div class="posted-link">Posted: <a href="${esc(d.posted_url)}" target="_blank" rel="noopener">${esc(d.posted_url)}</a></div>` : ''}
    <div class="actions">
      ${d.status === 'posted'
        ? `<button data-act="unpost">Mark unposted</button><button data-act="edit">Edit</button><button data-act="open">Open</button>`
        : `<button class="go" data-act="${canPost ? 'post' : 'approve'}" ${over ? 'disabled title="Over the limit — edit it first"' : ''}>${canPost ? 'Post it' : 'Approve'}</button>
           <button data-act="sendback">Send back</button>
           <button data-act="edit">Edit</button>`}
    </div>
  </article>`;
}

// ---------- render ----------
const VIEWS = [['pending', 'Pending review'], ['approved', 'Approved'], ['sent_back', 'Sent back'], ['posted', 'Posted']];

function visible() {
  const q = state.q.toLowerCase();
  return state.drafts.filter(d => d.status === state.view
    && (state.platform === 'all' || d.platform === state.platform)
    && (!q || (d.body + ' ' + (d.title || '') + ' ' + d.id).toLowerCase().includes(q)));
}

function render() {
  const byStatus = s => state.drafts.filter(d => d.status === s).length;
  $('nav').innerHTML = VIEWS.map(([k, label]) =>
    `<button class="nav-item" data-view="${k}" aria-current="${state.view === k}">${label}<span class="count">${byStatus(k)}</span></button>`).join('');
  $('accounts').innerHTML = Object.entries(state.platforms).map(([k, c]) =>
    `<div class="account"><span class="swatch" style="background:${esc(c.chip)}"></span>${esc(c.label)}</div>`).join('');

  const inView = state.drafts.filter(d => d.status === state.view);
  const counts = {};
  inView.forEach(d => counts[d.platform] = (counts[d.platform] || 0) + 1);
  $('filters').innerHTML = [`<button class="chip" data-plat="all" aria-pressed="${state.platform === 'all'}">All (${inView.length})</button>`]
    .concat(Object.entries(counts).map(([k, n]) =>
      `<button class="chip" data-plat="${k}" style="background:${state.platform === k ? '' : esc((state.platforms[k] || {}).chip || '#E8E6DE')}" aria-pressed="${state.platform === k}">${esc((state.platforms[k] || {}).label || k)} (${n})</button>`)).join('');

  $('view-title').textContent = (VIEWS.find(v => v[0] === state.view) || [, ''])[1];
  const over = inView.filter(d => { const c = state.platforms[d.platform] || {}; return c.limit && count(d.body, d.platform) > c.limit; }).length;
  $('summary').innerHTML = `<span>${inView.length} ${inView.length === 1 ? 'draft' : 'drafts'} · ${state.view.replace('_', ' ')}</span>
    <span class="sub">${over ? over + ' over the limit · ' : ''}Manual posting — approve, then copy and paste</span>`;

  const list = visible();
  $('grid').innerHTML = list.length ? list.map(card).join('')
    : `<div class="empty">Nothing here.${state.view === 'pending' ? '<br><br>Generate drafts from a finished run:<br><code>python3 social/gen_drafts.py &lt;RUN_ID&gt;</code>' : ''}</div>`;
}

// ---------- persistence ----------
async function patch(id, body) {
  const res = await fetch(`/api/drafts/${encodeURIComponent(id)}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  if (!res.ok) { toast('Save failed — draft left unchanged'); throw new Error(await res.text()); }
  const saved = await res.json();
  state.drafts = state.drafts.map(d => d.id === saved.id ? saved : d);
  render();
  return saved;
}

let toastTimer;
function toast(msg) {
  const el = $('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
}

// ---------- post walkthrough ----------
// Clipboard write and window.open must both be issued inside the click that triggered
// them. Awaiting anything first spends the user activation and the popup gets blocked.
function composeUrl(d, cfg) {
  if (!cfg.compose) return '';
  return cfg.compose
    .replace('{text}', encodeURIComponent(d.body))
    .replace('{title}', encodeURIComponent(d.title || ''))
    .replace('{subreddit}', encodeURIComponent(d.subreddit || 'LocalLLaMA'));
}

function openPostModal(d) {
  const cfg = state.platforms[d.platform] || {};
  const dlg = $('post-modal');
  const steps = (cfg.steps || []).map((s, i) =>
    `<div class="step" data-step="${i}"><span class="n">${i + 1}</span><div class="txt">${esc(s)}</div></div>`).join('');
  dlg.innerHTML = `
    <div class="m-head"><h2>Post to ${esc(cfg.label || d.platform)}</h2><button class="x" data-act="close">✕</button></div>
    <div class="m-body">
      ${cfg.prefill ? '' : `<div class="warnbox">${esc(cfg.label)} has no prefill URL. The text goes on your clipboard and the page opens blank — paste it yourself.</div>`}
      ${d.media && d.media.length ? `<div class="medialist"><b>Attach by hand:</b><br>${d.media.map(m => `<code>${esc(m)}</code>`).join('<br>')}</div>` : ''}
      <div class="field"><label>What gets copied</label>
        <textarea id="post-body" readonly>${esc(d.body)}</textarea></div>
      ${d.title ? `<div class="field"><label>Title</label><input type="text" id="post-title" readonly value="${esc(d.title)}"></div>` : ''}
      <div style="display:flex; gap:8px; flex-wrap:wrap">
        ${d.title ? '<button class="btn plain" data-act="copy-title">Copy title</button>' : ''}
        <button class="btn" data-act="copy-open">Copy body &amp; open ${esc(cfg.label)} ↗</button>
      </div>
      ${steps}
      <div class="field"><label>Paste the post URL back here</label>
        <input type="url" id="posted-url" placeholder="https://..." value="${esc(d.posted_url || '')}"></div>
    </div>
    <div class="m-foot">
      <button class="btn plain" data-act="close">Not yet</button>
      <button class="btn" data-act="mark-posted">Mark as posted</button>
    </div>`;

  dlg.onclick = event => {
    const act = event.target.closest('[data-act]')?.dataset.act;
    if (!act) return;
    if (act === 'close') return dlg.close();
    if (act === 'copy-title') {
      navigator.clipboard.writeText(d.title || '').then(() => toast('Title copied'), () => toast('Copy failed'));
      return;
    }
    if (act === 'copy-open') {
      // Both calls stay in the gesture. Do not await between them.
      const copied = navigator.clipboard.writeText(d.body);
      const url = composeUrl(d, cfg);
      const win = url ? window.open(url, '_blank', 'noopener') : null;
      dlg.querySelectorAll('.step').forEach((el, i) => { if (i < 2) el.classList.add('done'); });
      copied.then(
        () => toast(win ? 'Copied — ' + (cfg.label) + ' opened' : 'Copied. Popup blocked, open it yourself.'),
        () => toast('Could not reach the clipboard — select the text and copy it'));
      if (url && !win) toast('Popup blocked. Allow popups for 127.0.0.1, or open ' + cfg.label + ' yourself.');
      return;
    }
    if (act === 'mark-posted') {
      const url = dlg.querySelector('#posted-url').value.trim();
      if (url && !/^https?:\/\//i.test(url)) return toast('That does not look like a URL');
      patch(d.id, {status: 'posted', posted_url: url, posted_at: new Date().toISOString()})
        .then(() => { dlg.close(); toast('Marked as posted'); }).catch(() => {});
    }
  };
  dlg.showModal();
}

function openEditModal(d) {
  const cfg = state.platforms[d.platform] || {};
  const dlg = $('edit-modal');
  dlg.innerHTML = `
    <div class="m-head"><h2>Edit — ${esc(cfg.label || d.platform)}</h2><button class="x" data-act="close">✕</button></div>
    <div class="m-body">
      ${d.title !== undefined && d.platform === 'reddit' ? `<div class="field"><label>Title</label><input type="text" id="e-title" value="${esc(d.title || '')}"></div>` : ''}
      <div class="field"><label>Body</label><textarea id="e-body">${esc(d.body)}</textarea>
        <div class="count"><span id="e-count"></span><span>${esc(cfg.label || '')}</span></div></div>
    </div>
    <div class="m-foot"><button class="btn plain" data-act="close">Cancel</button><button class="btn" data-act="save">Save</button></div>`;
  const ta = dlg.querySelector('#e-body');
  const tick = () => {
    const used = count(ta.value, d.platform);
    const over = cfg.limit && used > cfg.limit;
    dlg.querySelector('#e-count').innerHTML = `<span class="${over ? 'over' : ''}">${used}${cfg.limit ? ' / ' + cfg.limit : ''} ${cfg.unit === 'graphemes' ? 'graphemes' : 'chars'}</span>`;
  };
  ta.oninput = tick; tick();
  dlg.onclick = event => {
    const act = event.target.closest('[data-act]')?.dataset.act;
    if (act === 'close') dlg.close();
    if (act === 'save') {
      const body = {body: ta.value};
      const title = dlg.querySelector('#e-title');
      if (title) body.title = title.value;
      patch(d.id, body).then(() => { dlg.close(); toast('Saved'); }).catch(() => {});
    }
  };
  dlg.showModal();
}

// ---------- events ----------
document.addEventListener('click', event => {
  const nav = event.target.closest('[data-view]');
  if (nav) { state.view = nav.dataset.view; state.platform = 'all'; return render(); }
  const chip = event.target.closest('[data-plat]');
  if (chip) { state.platform = chip.dataset.plat; return render(); }

  const button = event.target.closest('.actions button');
  if (!button) return;
  const d = state.drafts.find(x => x.id === button.closest('.draft').dataset.id);
  if (!d) return;
  const act = button.dataset.act;
  if (act === 'approve') patch(d.id, {status: 'approved', note: ''}).then(() => toast('Approved — Post it when ready')).catch(() => {});
  if (act === 'post') openPostModal(d);
  if (act === 'edit') openEditModal(d);
  if (act === 'unpost') patch(d.id, {status: 'approved', posted_url: '', posted_at: ''}).catch(() => {});
  if (act === 'open') window.open(d.posted_url, '_blank', 'noopener');
  if (act === 'sendback') {
    const note = prompt('What should change?', d.note || '');
    if (note !== null) patch(d.id, {status: 'sent_back', note}).then(() => toast('Sent back')).catch(() => {});
  }
});
$('search').addEventListener('input', e => { state.q = e.target.value; render(); });

(async function load() {
  try {
    const data = await (await fetch('/api/drafts')).json();
    state.drafts = data.drafts;
    state.platforms = data.platforms;
    render();
  } catch (err) {
    $('grid').innerHTML = `<div class="empty">Could not load drafts: ${esc(err.message)}</div>`;
  }
})();
