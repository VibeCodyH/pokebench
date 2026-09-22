// PokeBench social review. Renders each draft as the post it is about to become, then
// walks a manual copy/paste publish. It holds no account credential: its whole job is to
// get the right text onto the clipboard and the right page onto the screen, in that order.
// The one exception is Discord, which posts from here through a channel webhook, because a
// webhook writes to exactly one channel and reads nothing.
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const URL_RE = /https?:\/\/[^\s<]+/g;

let state = {drafts: [], platforms: {}, view: 'pending', platform: 'all', q: '',
             schedule: {entries: [], unscheduled: [], source: ''}};

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

// ---------- release schedule ----------
// One video a day. Sep 18 shipped five uploads and four of them landed at 1 view or fewer;
// Sep 20 put a real Brock win next to the record-setter and it drew 3. The server refuses a
// clashing PLANNED date, so this view's job is to make the free days obvious beforehand.
const TODAY = () => new Date().toISOString().slice(0, 10);
const daysBetween = (a, b) => Math.round((Date.parse(b + 'T00:00:00') - Date.parse(a + 'T00:00:00')) / 86400000);

function nextFreeDate() {
  const taken = new Set(state.schedule.entries.map(e => e.date).filter(Boolean));
  const day = new Date(TODAY() + 'T00:00:00');
  for (let i = 0; i < 60; i++) {
    const iso = day.toISOString().slice(0, 10);
    if (!taken.has(iso)) return iso;
    day.setDate(day.getDate() + 1);
  }
  return TODAY();
}

function renderSchedule() {
  const entries = state.schedule.entries;
  const published = entries.filter(d => d.status === 'published');
  const planned = entries.filter(d => d.status !== 'published');
  const last = published.map(d => d.date).filter(Boolean).sort().pop() || '';
  const gap = last ? daysBetween(last, TODAY()) : null;
  const free = nextFreeDate();

  // Count per day so a doubled-up day reads as the mistake it is, not a coincidence.
  const perDay = {};
  entries.forEach(d => { if (d.date) perDay[d.date] = (perDay[d.date] || 0) + 1; });

  const row = d => {
    const n = perDay[d.date] || 0;
    const dateCell = esc(d.date || 'unset') + (n > 1 ? ' <i>' + n + ' that day</i>' : '');
    const watch = d.youtube_url
      ? '<a href="' + esc(d.youtube_url) + '" target="_blank" rel="noopener">watch</a>' : '';
    const acts = d.status === 'published' ? watch
      : watch + '<button data-sched-drop="' + esc(d.run_id) + '">Drop</button>'
             + '<button data-sched-pub="' + esc(d.run_id) + '">Mark published</button>';
    return '<div class="srow ' + (d.status === 'published' ? 'is-pub' : '') + '">'
      + '<span class="sdate ' + (n > 1 ? 'clash' : '') + '">' + dateCell + '</span>'
      + '<span class="sname">' + esc(d.display_name || d.run_id) + '</span>'
      + '<span class="sstate">' + esc(d.status) + '</span>'
      + '<span class="sact">' + acts + '</span></div>';
  };

  const pending = state.schedule.unscheduled.map(r => {
    const sub = esc(r.termination_reason || '') + (r.turns_used ? ' · ' + r.turns_used + 't' : '');
    return '<div class="srow">'
      + '<input class="sinput" type="date" value="' + esc(free) + '" data-for="' + esc(r.run_id) + '">'
      + '<span class="sname">' + esc(r.display_name || r.run_id) + '<i>' + sub + '</i></span>'
      + '<span class="sstate">' + (r.youtube_url ? 'has a video' : 'no video yet') + '</span>'
      + '<span class="sact"><button data-sched-add="' + esc(r.run_id) + '">Schedule</button></span>'
      + '</div>';
  }).join('');

  $('schedule').innerHTML = '<div class="sbar">'
    + '<div><b>Last upload</b> ' + (last
        ? esc(last) + (gap === 0 ? ' · today' : ' · ' + gap + ' day' + (gap === 1 ? '' : 's') + ' ago')
        : 'none recorded') + '</div>'
    + '<div><b>Next free day</b> ' + esc(free) + '</div>'
    + '<div class="sub">' + published.length + ' published · ' + planned.length + ' planned</div>'
    + '</div>'
    + '<h3 class="shead">Planned</h3>'
    + (planned.length ? planned.map(row).join('') : '<div class="empty small">Nothing scheduled.</div>')
    + '<h3 class="shead">Not scheduled yet</h3>'
    + (pending || '<div class="empty small">Every board run is on the schedule.</div>')
    + '<h3 class="shead">Published</h3>'
    + published.slice().reverse().map(row).join('')
    + (state.schedule.source ? '<p class="ssource">' + esc(state.schedule.source) + '</p>' : '');
}

// The server owns the one-a-day rule and answers 409 with the run already holding the day.
// Surfacing its message verbatim beats re-deriving the reason in the browser.
async function saveSchedule(runId, body) {
  const res = await fetch('/api/schedule/' + encodeURIComponent(runId), {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { toast(data.error || 'Save failed'); return false; }
  state.schedule = data;
  render();
  return true;
}

// ---------- posting schedule ----------

// A draft's day lives in post_on. Drafts written before that field wear their date in the id,
// which is where gen_drafts puts it, so read that before falling back to when it was created.
const postDate = d => d.post_on || (/^(\d{4}-\d{2}-\d{2})-/.exec(d.id) || [, ''])[1]
  || String(d.created || '').slice(0, 10);

const dayHead = iso => new Date(iso + 'T00:00:00')
  .toLocaleDateString('en-US', {weekday: 'long', month: 'short', day: 'numeric'});

function whenLabel(iso) {
  const n = daysBetween(TODAY(), iso);
  if (n === 0) return 'today';
  if (n === 1) return 'tomorrow';
  if (n > 1) return 'in ' + n + ' days';
  return n === -1 ? 'yesterday' : Math.abs(n) + ' days ago';
}

function postingRow(d) {
  const cfg = state.platforms[d.platform] || {};
  const line = bodyWithoutTrailingUrl(d.body).split('\n').filter(Boolean)[0] || '';
  const n = (d.media || []).length;
  const media = n ? n + (n === 1 ? ' asset' : ' assets') : 'text only';
  const acts = d.status === 'posted'
    ? (d.posted_url ? '<a href="' + esc(d.posted_url) + '" target="_blank" rel="noopener">open</a>' : '')
    : (d.status === 'pending' ? '<button data-pp-approve="' + esc(d.id) + '">Approve</button>' : '')
      + '<button data-pp-post="' + esc(d.id) + '">Post it</button>';
  return '<div class="srow' + (d.status === 'posted' ? ' is-pub' : '') + '">'
    + '<input class="sinput" type="date" value="' + esc(postDate(d)) + '" data-pp-date="' + esc(d.id) + '">'
    + '<span class="sname">' + esc(cfg.label || d.platform)
      + '<i>' + esc(line.slice(0, 64)) + (line.length > 64 ? '…' : '') + '</i></span>'
    + '<span class="sstate">' + esc(STATE_LABEL[d.status] || d.status) + ' · ' + media + '</span>'
    + '<span class="sact">' + acts + '</span></div>';
}

function renderPosting() {
  const today = TODAY();
  const queue = state.drafts.filter(d => d.status !== 'posted');
  const undated = queue.filter(d => !postDate(d));
  const dated = queue.filter(d => postDate(d));
  const overdue = dated.filter(d => postDate(d) < today);
  const ahead = dated.filter(d => postDate(d) >= today);
  const days = [...new Set(ahead.map(postDate))].sort();
  const posted = state.drafts.filter(d => d.status === 'posted')
    .sort((a, b) => postDate(b).localeCompare(postDate(a)));

  const section = iso => '<h3 class="shead">' + esc(dayHead(iso))
    + ' <i>' + esc(whenLabel(iso)) + '</i></h3>'
    + ahead.filter(d => postDate(d) === iso).map(postingRow).join('');

  $('schedule').innerHTML = '<div class="sbar">'
    + '<div><b>Queued</b> ' + queue.length + ' to post</div>'
    + '<div><b>Next up</b> ' + (days[0] ? esc(days[0]) + ' · ' + esc(whenLabel(days[0])) : 'nothing scheduled') + '</div>'
    + '<div class="sub">' + overdue.length + ' overdue · ' + posted.length + ' posted</div>'
    + '</div>'
    + (overdue.length
        ? '<h3 class="shead">Overdue</h3>' + overdue.sort((a, b) => postDate(a).localeCompare(postDate(b)))
            .map(postingRow).join('')
        : '')
    + (days.length ? days.map(section).join('')
        : '<div class="empty small">Nothing on the calendar. Give a draft a date to put it here.</div>')
    + (undated.length ? '<h3 class="shead">No date yet</h3>' + undated.map(postingRow).join('') : '')
    + (posted.length ? '<h3 class="shead">Already out</h3>' + posted.slice(0, 12).map(postingRow).join('') : '');
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
  const plannedCount = state.schedule.entries.filter(d => d.status !== 'published').length;
  const toPost = state.drafts.filter(d => d.status !== 'posted').length;
  $('nav-release').innerHTML =
    `<button class="nav-item" data-view="schedule" aria-current="${state.view === 'schedule'}">Video schedule<span class="count">${plannedCount}</span></button>`
    + `<button class="nav-item" data-view="posting" aria-current="${state.view === 'posting'}">Posting schedule<span class="count">${toPost}</span></button>`;
  $('accounts').innerHTML = Object.entries(state.platforms).map(([k, c]) =>
    `<div class="account"><span class="swatch" style="background:${esc(c.chip)}"></span>${esc(c.label)}</div>`).join('');

  // Both schedules are calendars rather than filtered piles of drafts, so they replace the grid.
  const onSchedule = state.view === 'schedule';
  const onPosting = state.view === 'posting';
  $('schedule').hidden = !(onSchedule || onPosting);
  $('grid').hidden = onSchedule || onPosting;
  $('filters').hidden = onSchedule || onPosting;
  $('search').hidden = onSchedule || onPosting;
  if (onSchedule) {
    $('view-title').textContent = 'Video schedule';
    $('summary').innerHTML = '<span>One video a day</span><span class="sub">The server refuses a planned date that already has a video</span>';
    return renderSchedule();
  }
  if (onPosting) {
    $('view-title').textContent = 'Posting schedule';
    $('summary').innerHTML = '<span>What goes out, and when</span><span class="sub">Change a date to move a post; nothing posts itself</span>';
    return renderPosting();
  }

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

// Discord is the only platform with a publisher behind it, so its Post it button posts.
// Everything else opens the copy-and-paste walkthrough, because nothing here holds an account.
function postIt(d) {
  if (d.platform !== 'discord') return openPostModal(d);
  return void publish(d);
}

async function publish(d) {
  const res = await fetch(`/api/drafts/${encodeURIComponent(d.id)}/publish`, {method: 'POST'});
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return toast(data.error || 'Post failed — draft left alone');
  state.drafts = state.drafts.map(x => x.id === data.id ? data : x);
  render();
  toast('Posted to Discord');
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

  const add = event.target.closest('[data-sched-add]');
  if (add) {
    const id = add.dataset.schedAdd;
    const input = document.querySelector(`[data-for="${CSS.escape(id)}"]`);
    const date = input ? input.value : '';
    if (!date) return toast('Pick a date first');
    return void saveSchedule(id, {date, status: 'planned'}).then(ok => ok && toast('Scheduled for ' + date));
  }
  const drop = event.target.closest('[data-sched-drop]');
  if (drop) return void saveSchedule(drop.dataset.schedDrop, {date: ''}).then(ok => ok && toast('Unscheduled'));
  const pub = event.target.closest('[data-sched-pub]');
  if (pub) {
    const entry = state.schedule.entries.find(d => d.run_id === pub.dataset.schedPub);
    if (!entry) return;
    const url = prompt('YouTube URL (optional)', entry.youtube_url || '');
    if (url === null) return;
    return void saveSchedule(entry.run_id, {date: entry.date, status: 'published', youtube_url: url.trim()})
      .then(ok => ok && toast('Marked published'));
  }

  const ppApprove = event.target.closest('[data-pp-approve]');
  if (ppApprove) {
    return void patch(ppApprove.dataset.ppApprove, {status: 'approved', note: ''})
      .then(() => toast('Approved')).catch(() => {});
  }
  const ppPost = event.target.closest('[data-pp-post]');
  if (ppPost) {
    const draft = state.drafts.find(x => x.id === ppPost.dataset.ppPost);
    return void (draft && postIt(draft));
  }

  const button = event.target.closest('.actions button');
  if (!button) return;
  const d = state.drafts.find(x => x.id === button.closest('.draft').dataset.id);
  if (!d) return;
  const act = button.dataset.act;
  if (act === 'approve') patch(d.id, {status: 'approved', note: ''}).then(() => toast('Approved — Post it when ready')).catch(() => {});
  if (act === 'post') postIt(d);
  if (act === 'edit') openEditModal(d);
  if (act === 'unpost') patch(d.id, {status: 'approved', posted_url: '', posted_at: ''}).catch(() => {});
  if (act === 'open') window.open(d.posted_url, '_blank', 'noopener');
  if (act === 'sendback') {
    const note = prompt('What should change?', d.note || '');
    if (note !== null) patch(d.id, {status: 'sent_back', note}).then(() => toast('Sent back')).catch(() => {});
  }
});

// Moving a post is a date edit, so it commits on change rather than behind a save button.
document.addEventListener('change', event => {
  const input = event.target.closest('[data-pp-date]');
  if (!input) return;
  const date = input.value;
  patch(input.dataset.ppDate, {post_on: date})
    .then(() => toast(date ? 'Moved to ' + date : 'Date cleared'))
    .catch(() => {});
});
$('search').addEventListener('input', e => { state.q = e.target.value; render(); });

(async function load() {
  try {
    const [data, schedule] = await Promise.all([
      (await fetch('/api/drafts')).json(),
      (await fetch('/api/schedule')).json(),
    ]);
    state.drafts = data.drafts;
    state.platforms = data.platforms;
    state.schedule = schedule;
    render();
  } catch (err) {
    $('grid').innerHTML = `<div class="empty">Could not load drafts: ${esc(err.message)}</div>`;
  }
})();
