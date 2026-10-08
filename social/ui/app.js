// PokeBench social review. Renders each draft as the post it is about to become, then
// walks a manual copy/paste publish. It holds no account credential: its whole job is to
// get the right text onto the clipboard and the right page onto the screen, in that order.
// The one exception is Discord, which posts from here through a channel webhook, because a
// webhook writes to exactly one channel and reads nothing.
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const URL_RE = /https?:\/\/[^\s<]+/g;

let state = {drafts: [], platforms: {}, view: 'pending', platform: 'all', q: '',
             schedule: {entries: [], unscheduled: [], source: ''}, storyboards: []};

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

// Reddit and Shorts also cap the title, and an over-long title is rejected just like a body.
function overLimit(d) {
  const cfg = state.platforms[d.platform] || {};
  return Boolean((cfg.limit && count(d.body, d.platform) > cfg.limit)
    || (cfg.title_limit && (d.title || '').length > cfg.title_limit));
}

const firstUrl = text => (String(text).match(URL_RE) || [])[0] || '';
// Related video only accepts a video from the channel, so a run with no VOD yet has nothing
// to link (its draft link falls back to pokebench.tv).
const isYouTube = url => /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\//i.test(url || '');
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
  youtube_shorts(d) {
    // The Shorts player shows the title and the Related video pill; the description sits
    // behind a tap, and its links are not clickable, so the pill is the real link.
    const related = isYouTube(d.link) ? d.link.replace(/^https?:\/\/(www\.)?/, '') : '';
    return `<div class="pv pv-youtube_shorts">
      <div class="poster">${d.media && d.media[0] ? `<img src="${esc(mediaUrl(d.media[0]))}" alt="">` : 'no clip attached — 9:16'}</div>
      <div class="rail"><span><i>👍</i>0</span><span><i>💬</i>0</span><span><i>↗</i>0</span></div>
      <div class="cap">
        ${related ? `<div class="rel">▶ Related video · ${esc(related)}</div>` : ''}
        <div class="nm">@pokebenchtv</div>
        <div class="ttl">${esc(d.title || '(no title)')}</div>
        <div class="hide">description hidden behind a tap</div>
      </div>
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
const STATE_LABEL = {pending: 'Needs review', approved: 'Approved', sent_back: 'Sent back', posted: 'Posted',
                     archived: 'Archived'};

function card(d) {
  const cfg = state.platforms[d.platform] || {label: d.platform, limit: 0};
  const used = count(d.body, d.platform);
  const over = overLimit(d);
  const titleOver = cfg.title_limit && (d.title || '').length > cfg.title_limit;
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
      <span class="${over ? 'over' : ''}">${used}${cfg.limit ? ' / ' + cfg.limit : ''} ${cfg.unit === 'graphemes' ? 'graphemes' : 'chars'}${cfg.title_limit && d.title ? ` · <span class="${titleOver ? 'over' : ''}">title ${d.title.length} / ${cfg.title_limit}</span>` : ''}${over ? ' — too long' : ''}</span>
      <span>${d.media && d.media.length ? d.media.length + ' file' + (d.media.length > 1 ? 's' : '') : 'No media'}</span>
    </div>
    ${d.note ? `<div class="note"><b>SENT BACK</b>${esc(d.note)}</div>` : ''}
    ${d.posted_url ? `<div class="posted-link">Posted: <a href="${esc(d.posted_url)}" target="_blank" rel="noopener">${esc(d.posted_url)}</a></div>` : ''}
    <div class="actions">
      ${d.status === 'posted'
        ? `<button data-act="unpost">Mark unposted</button><button data-act="edit">Edit</button><button data-act="open">Open</button>`
        : d.status === 'archived'
        ? `<button class="go" data-act="restore">Restore</button><button data-act="edit">Edit</button><button data-act="retire">Retire</button>`
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
// Local date, not UTC: after 8 PM Eastern the UTC date is already tomorrow, which would make
// Skip jump a day and label tonight's posts as yesterday's.
const TODAY = () => new Date().toLocaleDateString('en-CA');
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

// ---------- moments ----------
// One post goes out as several drafts named <date>-<slug>-<platform> (x, bluesky, tiktok...).
// Skip / Archive / Retire act on the whole moment, so a post never goes out on half its
// platforms. The key is the id minus the platform, which never changes: keying on the post
// date would merge two different posts the day one of them is moved onto the other's day.
const slugOf = d => String(d.id).replace(/^\d{4}-\d{2}-\d{2}-/, '').replace(new RegExp('-' + d.platform + '$'), '');
const momentKey = d => String(d.id).replace(new RegExp('-' + d.platform + '$'), '');
const momentOf = (d, keep) => state.drafts.filter(x => momentKey(x) === momentKey(d) && keep(x));
// Still headed out: not posted, not parked.
const live = d => d.status !== 'posted' && d.status !== 'archived';
const addDays = (iso, n) => {
  const t = new Date(iso + 'T00:00:00Z');
  t.setUTCDate(t.getUTCDate() + n);
  return t.toISOString().slice(0, 10);
};

// First day on or after `from` with no post on it. A posted draft still holds its day (that
// slot went to something); an archived one does not, it is off the calendar.
function nextFreePostDay(from, moving) {
  const ids = new Set(moving.map(d => d.id));
  const taken = new Set(state.drafts.filter(d => d.status !== 'archived' && !ids.has(d.id)).map(postDate));
  let day = from;
  while (taken.has(day)) day = addDays(day, 1);
  return day;
}

// One at a time: patch() throws on the first failure, so a refusal stops the rest instead of
// leaving a moment split across two days without saying so.
async function patchAll(drafts, body) {
  for (const d of drafts) await patch(d.id, body);
}

// One moment action at a time. Two Skips fired before either save lands would both see the
// same day as free and both take it.
let momentBusy = false;
async function oneAtATime(job) {
  if (momentBusy) return toast('Still saving the last one');
  momentBusy = true;
  try { await job(); } catch { /* patch() already said why */ } finally { momentBusy = false; }
}

function skipMoment(d) {
  return oneAtATime(async () => {
    const group = momentOf(d, live);
    const today = TODAY();
    const day = nextFreePostDay(addDays(postDate(d) > today ? postDate(d) : today, 1), group);
    await patchAll(group, {post_on: day});
    toast('Moved to ' + day + ' · ' + whenLabel(day));
  });
}

function archiveMoment(d) {
  return oneAtATime(async () => {
    await patchAll(momentOf(d, live), {status: 'archived'});
    toast('Archived — find it under Archived');
  });
}

function restoreMoment(d) {
  const group = momentOf(d, x => x.status === 'archived');
  const day = (prompt('Post on which day? (YYYY-MM-DD)', nextFreePostDay(TODAY(), group)) ?? '').trim();
  if (!day) return;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return toast('Use YYYY-MM-DD');
  // Back to review rather than straight to approved: it has been parked, read it again.
  return oneAtATime(async () => {
    await patchAll(group, {status: 'pending', post_on: day});
    toast('Restored to ' + day + ' · needs review');
  });
}

function retireMoment(group) {
  if (!group.length) return;
  const names = group.map(d => (state.platforms[d.platform] || {}).label || d.platform).join(', ');
  if (!confirm('Retire "' + slugOf(group[0]) + '" (' + names + ')?\n\nThe drafts move to drafts/_archive/ and leave the dashboard.')) return;
  return oneAtATime(async () => {
    let failed = '';
    for (const d of group) {
      const res = await fetch('/api/drafts/' + encodeURIComponent(d.id) + '/retire', {method: 'POST'});
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { failed = data.error || 'Retire failed'; break; }
      state.drafts = state.drafts.filter(x => x.id !== d.id);
    }
    render();
    toast(failed || 'Retired');
  });
}

// The moment's header row, followed by one row per platform draft in it.
function momentRows(list) {
  const groups = new Map();
  list.forEach(d => {
    const key = momentKey(d);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(d);
  });
  return [...groups.values()].map(g => '<div class="mrow"><span class="mname">'
    + esc(slugOf(g[0]).replace(/-/g, ' ')) + '</span>'
    + '<button data-m-skip="' + esc(g[0].id) + '" title="Move every platform to the next day with nothing on it">Skip</button>'
    + '<button data-m-archive="' + esc(g[0].id) + '" title="Park it off the calendar for later">Archive</button>'
    + '<button class="retire" data-m-retire="' + esc(g[0].id) + '" title="Remove it for good">Retire</button></div>'
    + g.map(postingRow).join('')).join('');
}

function renderPosting() {
  const today = TODAY();
  const queue = state.drafts.filter(live);
  const undated = queue.filter(d => !postDate(d));
  const dated = queue.filter(d => postDate(d));
  const overdue = dated.filter(d => postDate(d) < today);
  const ahead = dated.filter(d => postDate(d) >= today);
  const days = [...new Set(ahead.map(postDate))].sort();
  const posted = state.drafts.filter(d => d.status === 'posted')
    .sort((a, b) => postDate(b).localeCompare(postDate(a)));

  const section = iso => '<h3 class="shead">' + esc(dayHead(iso))
    + ' <i>' + esc(whenLabel(iso)) + '</i></h3>'
    + momentRows(ahead.filter(d => postDate(d) === iso));

  $('schedule').innerHTML = '<div class="sbar">'
    + '<div><b>Queued</b> ' + queue.length + ' to post</div>'
    + '<div><b>Next up</b> ' + (days[0] ? esc(days[0]) + ' · ' + esc(whenLabel(days[0])) : 'nothing scheduled') + '</div>'
    + '<div class="sub">' + overdue.length + ' overdue · ' + posted.length + ' posted</div>'
    + '</div>'
    + (overdue.length
        ? '<h3 class="shead">Overdue</h3>' + momentRows(overdue.sort((a, b) => postDate(a).localeCompare(postDate(b))))
        : '')
    + (days.length ? days.map(section).join('')
        : '<div class="empty small">Nothing on the calendar. Give a draft a date to put it here.</div>')
    + (undated.length ? '<h3 class="shead">No date yet</h3>' + momentRows(undated) : '')
    + (posted.length ? '<h3 class="shead">Already out</h3>' + posted.slice(0, 12).map(postingRow).join('') : '');
}

// ---------- storyboards ----------
// A storyboard is the plan for one short: its beats, in order. Each beat carries what one
// segment of a multi-segment clip build needs: which shot and turn, where to cut in and for how
// long, who is talking, what is on screen, the narrator's line, the model's own words, keycap
// chips, zoom. Approving one is the go-ahead to build the clip from it; the dashboard does not
// render video.
const BOARD_LABEL = {draft: 'Needs review', approved: 'Approved', sent_back: 'Sent back'};
const BLANK_BEAT = {id: '', label: '', turn: '', shot: '', in: '', dur: '', text: '', voice: '', quote: '', chips: '', zoom: ''};
const runtime = beats => (beats || []).reduce((sum, b) => sum + (Number(b.dur) || 0), 0);

function renderBoards() {
  const boards = state.storyboards;
  const open = boards.filter(b => b.status !== 'approved');
  const approved = boards.filter(b => b.status === 'approved');
  const row = b => '<div class="srow">'
    + '<span class="sdate">' + runtime(b.beats).toFixed(1) + 's</span>'
    + '<span class="sname">' + esc(b.title || b.id) + '<i>' + esc(b.model || b.run_id || '') + '</i></span>'
    + '<span class="sstate">' + esc(b.error ? 'unreadable' : (BOARD_LABEL[b.status] || b.status))
      + ' · ' + (b.beats || []).length + ' beats' + (b.clip ? ' · built' : '') + '</span>'
    + '<span class="sact">' + (b.error ? '' : '<button data-board-open="' + esc(b.id) + '">Open</button>') + '</span></div>';
  $('schedule').innerHTML = '<div class="sbar">'
    + '<div><b>To review</b> ' + open.length + '</div>'
    + '<div><b>Approved</b> ' + approved.length + '</div>'
    + '<button class="btn" data-board-new>New storyboard</button>'
    + '</div>'
    + '<h3 class="shead">Needs review</h3>'
    + (open.length ? open.map(row).join('') : '<div class="empty small">Nothing waiting on you.</div>')
    + (approved.length ? '<h3 class="shead">Approved — ready to build</h3>' + approved.map(row).join('') : '');
}

async function saveBoard(id, body) {
  const res = await fetch('/api/storyboards/' + encodeURIComponent(id), {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { toast(data.error || 'Save failed — storyboard left unchanged'); return null; }
  state.storyboards = state.storyboards.map(b => b.id === data.id ? data : b);
  render();
  return data;
}

async function newBoard() {
  const title = prompt('What is the clip? (a working title)');
  if (!title || !title.trim()) return;
  const res = await fetch('/api/storyboards', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({title: title.trim()}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return toast(data.error || 'Could not create it');
  state.storyboards = state.storyboards.concat(data);
  render();
  openBoardModal(data);
}

function openBoardModal(board) {
  const dlg = $('board-modal');
  const meta = {title: board.title || '', run_id: board.run_id || '', model: board.model || ''};
  const beats = (board.beats || []).map(b => ({...BLANK_BEAT, ...b}));
  // Count edits rather than flag them: a save only clears what it actually sent, so typing
  // while it is in flight still counts as unsaved.
  let edits = 0, saved = 0;
  const dirty = () => edits !== saved;

  const input = (i, k, label, type = 'text', extra = '') =>
    `<label>${label}<input type="${type}" data-beat="${i}" data-k="${k}" value="${esc(beats[i][k] ?? '')}" ${extra}></label>`;
  const area = (i, k, label) =>
    `<label>${label}<textarea data-beat="${i}" data-k="${k}">${esc(beats[i][k] ?? '')}</textarea></label>`;
  const beatHtml = (b, i) => `<div class="beat">
      <div class="beat-head">
        <span class="n">${i + 1}</span>
        ${input(i, 'id', 'Beat id', 'text', 'placeholder="hook"')}
        ${input(i, 'label', 'Who is talking', 'text', 'list="beat-labels"')}
        ${input(i, 'turn', 'Turn', 'number', 'min="0" step="1"')}
        ${input(i, 'shot', 'Shot', 'text', 'placeholder="S171"')}
        ${input(i, 'in', 'In (s)', 'number', 'min="0" step="0.1"')}
        ${input(i, 'dur', 'Length (s)', 'number', 'min="0" step="0.1"')}
        <div class="moves"><button data-move="-1" data-i="${i}" title="Move up">↑</button><button data-move="1" data-i="${i}" title="Move down">↓</button><button data-del="${i}" title="Delete beat">✕</button></div>
      </div>
      <div class="beat-copy">
        ${area(i, 'text', 'On-screen text')}
        ${area(i, 'voice', 'Narrator line')}
        <div>${area(i, 'quote', 'Model quote (verbatim)')}<button class="pull" data-pull="${i}" data-source="plan">Pull plan</button> <button class="pull" data-pull="${i}" data-source="thinking" title="The raw reasoning trace. Long: keep the lines you want, cut the rest.">Pull thinking</button></div>
      </div>
      <div class="beat-extra">
        ${input(i, 'chips', 'Keycap chips', 'text', 'placeholder="up up down down left right B A"')}
        ${input(i, 'zoom', 'Zoom', 'text', 'placeholder="what to punch in on"')}
      </div>
    </div>`;
  const totalText = () => beats.length + ' beats · ' + runtime(beats).toFixed(1) + 's';
  const content = () => ({...meta, beats});

  const draw = () => {
    const sentBack = board.status === 'sent_back' && board.note;
    dlg.innerHTML = `
      <div class="m-head"><h2>Storyboard — ${esc(meta.title || board.id)}</h2>
        <span class="state">${esc(BOARD_LABEL[board.status] || board.status)}</span>
        <button class="x" data-act="close">✕</button></div>
      <div class="m-body">
        ${sentBack ? `<div class="note"><b>SENT BACK</b>${esc(board.note)}</div>` : ''}
        ${board.clip ? `<div class="medialist"><b>Built:</b> <code>${esc(board.clip)}</code></div>` : ''}
        <div class="bmeta">
          <div class="field"><label>Title</label><input type="text" data-meta="title" value="${esc(meta.title)}"></div>
          <div class="field"><label>Run id</label><input type="text" data-meta="run_id" value="${esc(meta.run_id)}" placeholder="qwen3-8-27b-rvb-20261005_061425-rp0hw9i4"></div>
          <div class="field"><label>Model name</label><input type="text" data-meta="model" value="${esc(meta.model)}" placeholder="Qwen3.8 27B"></div>
        </div>
        <datalist id="beat-labels"><option value="NARRATOR">${meta.model ? `<option value="${esc(meta.model.toUpperCase())} IS THINKING">` : ''}</datalist>
        ${beats.length ? beats.map(beatHtml).join('')
          : '<div class="empty small">No beats yet. A beat is one segment of the clip: what is on screen, for how long, and who is talking.</div>'}
        <div><button class="btn plain" data-act="add">+ Add beat</button></div>
      </div>
      <div class="m-foot">
        <span class="btotal" id="b-total">${totalText()}</span>
        <button class="btn plain" data-act="sendback">Send back</button>
        <button class="btn plain" data-act="save">Save</button>
        <button class="btn" data-act="approve">Approve</button>
      </div>`;
  };

  dlg.oninput = event => {
    const el = event.target;
    if (el.dataset.meta) meta[el.dataset.meta] = el.value;
    else if (el.dataset.beat !== undefined) beats[Number(el.dataset.beat)][el.dataset.k] = el.value;
    else return;
    edits++;
    const total = dlg.querySelector('#b-total');
    if (total) total.textContent = totalText();
  };

  const store = async body => {
    const rev = edits;
    const result = await saveBoard(board.id, body);
    if (!result) return null;
    board = result;
    saved = rev;
    return result;
  };
  // Approve and Send back close the dialog, which would drop anything typed after they fired.
  const closeIfSaved = msg => {
    if (dirty()) { draw(); return toast(msg + ' — newer edits are not saved yet'); }
    dlg.close();
    toast(msg);
  };

  dlg.onclick = async event => {
    const el = event.target.closest('button');
    if (!el) return;
    if (el.dataset.move !== undefined) {
      const i = Number(el.dataset.i), j = i + Number(el.dataset.move);
      if (j < 0 || j >= beats.length) return;
      [beats[i], beats[j]] = [beats[j], beats[i]];
      edits++;
      return draw();
    }
    if (el.dataset.del !== undefined) {
      beats.splice(Number(el.dataset.del), 1);
      edits++;
      return draw();
    }
    if (el.dataset.pull !== undefined) {
      const beat = beats[Number(el.dataset.pull)];
      const runId = meta.run_id, turn = String(beat.turn ?? '');
      if (!runId || !turn) return toast('Set the run id and the beat\'s turn first');
      if (beat.quote && !confirm('Replace the quote that is there?')) return;
      const res = await fetch('/api/turn?run_id=' + encodeURIComponent(runId) + '&turn=' + encodeURIComponent(turn)
        + '&source=' + encodeURIComponent(el.dataset.source || 'plan'));
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return toast(data.error || 'Could not read the log');
      // The quote has to belong to the turn it sits under. If the beat moved on while the
      // log was being read, drop the answer rather than file it under the wrong turn.
      if (!beats.includes(beat) || meta.run_id !== runId || String(beat.turn ?? '') !== turn) {
        return toast('The run or turn changed while loading, pull it again');
      }
      beat.quote = data.quote;
      edits++;
      return draw();
    }
    const act = el.dataset.act;
    if (act === 'close') {
      if (dirty() && !confirm('Close without saving?')) return;
      return dlg.close();
    }
    if (act === 'add') {
      const last = beats[beats.length - 1];
      beats.push({...BLANK_BEAT, turn: last ? last.turn : '', shot: last ? last.shot : ''});
      edits++;
      return draw();
    }
    if (act === 'save') {
      if (await store(content())) { toast(board.status === 'draft' ? 'Saved — needs review' : 'Saved'); draw(); }
      return;
    }
    if (act === 'approve') {
      if (await store({...content(), status: 'approved', note: ''})) closeIfSaved('Approved — ready to build');
      return;
    }
    if (act === 'sendback') {
      const note = prompt('What should change?', board.note || '');
      if (note === null) return;
      if (await store({...content(), status: 'sent_back', note})) closeIfSaved('Sent back');
    }
  };

  // Escape closes a dialog without going through the ✕ button, so guard it the same way.
  dlg.oncancel = event => { if (dirty() && !confirm('Close without saving?')) event.preventDefault(); };
  draw();
  dlg.showModal();
}

// ---------- render ----------
const VIEWS = [['pending', 'Pending review'], ['approved', 'Approved'], ['sent_back', 'Sent back'], ['posted', 'Posted'],
               ['archived', 'Archived']];

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
  const toPost = state.drafts.filter(live).length;
  $('nav-release').innerHTML =
    `<button class="nav-item" data-view="schedule" aria-current="${state.view === 'schedule'}">Video schedule<span class="count">${plannedCount}</span></button>`
    + `<button class="nav-item" data-view="posting" aria-current="${state.view === 'posting'}">Posting schedule<span class="count">${toPost}</span></button>`;
  const boardsOpen = state.storyboards.filter(b => b.status !== 'approved').length;
  $('nav-clips').innerHTML =
    `<button class="nav-item" data-view="storyboards" aria-current="${state.view === 'storyboards'}">Storyboards<span class="count">${boardsOpen}</span></button>`;
  $('accounts').innerHTML = Object.entries(state.platforms).map(([k, c]) =>
    `<div class="account"><span class="swatch" style="background:${esc(c.chip)}"></span>${esc(c.label)}</div>`).join('');

  // The schedules and the storyboard list are not filtered piles of drafts, so they replace the grid.
  const onSchedule = state.view === 'schedule';
  const onPosting = state.view === 'posting';
  const onBoards = state.view === 'storyboards';
  const panel = onSchedule || onPosting || onBoards;
  $('schedule').hidden = !panel;
  $('grid').hidden = panel;
  $('filters').hidden = panel;
  $('search').hidden = panel;
  if (onBoards) {
    $('view-title').textContent = 'Storyboards';
    $('summary').innerHTML = '<span>Plan the short beat by beat</span><span class="sub">Approve a board and the clip gets built from it; editing it re-opens review</span>';
    return renderBoards();
  }
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
  const over = inView.filter(overLimit).length;
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
  // A Short's clickable link to the full run is Studio's Related video field, not the body.
  const related = d.platform === 'youtube_shorts' && isYouTube(d.link);
  dlg.innerHTML = `
    <div class="m-head"><h2>Post to ${esc(cfg.label || d.platform)}</h2><button class="x" data-act="close">✕</button></div>
    <div class="m-body">
      ${cfg.prefill ? '' : `<div class="warnbox">${esc(cfg.label)} has no prefill URL. The text goes on your clipboard and the page opens blank — paste it yourself.</div>`}
      ${d.media && d.media.length ? `<div class="medialist"><b>Attach by hand:</b><br>${d.media.map(m => `<code>${esc(m)}</code>`).join('<br>')}</div>` : ''}
      <div class="field"><label>What gets copied</label>
        <textarea id="post-body" readonly>${esc(d.body)}</textarea></div>
      ${d.title ? `<div class="field"><label>Title</label><input type="text" id="post-title" readonly value="${esc(d.title)}"></div>` : ''}
      ${related ? `<div class="field"><label>Related video (set in Studio after upload)</label><input type="text" id="post-related" readonly value="${esc(d.link)}"></div>` : ''}
      <div style="display:flex; gap:8px; flex-wrap:wrap">
        ${d.title ? '<button class="btn plain" data-act="copy-title">Copy title</button>' : ''}
        ${related ? '<button class="btn plain" data-act="copy-link">Copy link</button>' : ''}
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
    if (act === 'copy-link') {
      navigator.clipboard.writeText(d.link || '').then(() => toast('Link copied'), () => toast('Copy failed'));
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
      ${d.title !== undefined && (d.platform === 'reddit' || d.platform === 'youtube_shorts') ? `<div class="field"><label>Title</label><input type="text" id="e-title" value="${esc(d.title || '')}">
        ${cfg.title_limit ? '<div class="count"><span id="e-tcount"></span></div>' : ''}</div>` : ''}
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
  const ti = dlg.querySelector('#e-title');
  const tcount = dlg.querySelector('#e-tcount');
  if (ti && tcount) {
    const ttick = () => {
      const over = ti.value.length > cfg.title_limit;
      tcount.innerHTML = `<span class="${over ? 'over' : ''}">title ${ti.value.length} / ${cfg.title_limit}</span>`;
    };
    ti.oninput = ttick; ttick();
  }
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

  const moment = event.target.closest('[data-m-skip], [data-m-archive], [data-m-retire]');
  if (moment) {
    const m = moment.dataset;
    const draft = state.drafts.find(x => x.id === (m.mSkip || m.mArchive || m.mRetire));
    if (!draft) return;
    if (m.mSkip) return skipMoment(draft);
    if (m.mArchive) return archiveMoment(draft);
    return void retireMoment(momentOf(draft, live));
  }

  const boardOpen = event.target.closest('[data-board-open]');
  if (boardOpen) {
    const board = state.storyboards.find(b => b.id === boardOpen.dataset.boardOpen);
    return void (board && openBoardModal(board));
  }
  if (event.target.closest('[data-board-new]')) return void newBoard();

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
  if (act === 'restore') restoreMoment(d);
  if (act === 'retire') retireMoment(momentOf(d, x => x.status === 'archived'));
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
    const [data, schedule, boards] = await Promise.all([
      (await fetch('/api/drafts')).json(),
      (await fetch('/api/schedule')).json(),
      (await fetch('/api/storyboards')).json(),
    ]);
    state.drafts = data.drafts;
    state.platforms = data.platforms;
    state.schedule = schedule;
    state.storyboards = boards.storyboards;
    render();
  } catch (err) {
    $('grid').innerHTML = `<div class="empty">Could not load drafts: ${esc(err.message)}</div>`;
  }
})();
