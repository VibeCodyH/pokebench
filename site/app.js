// PokéBench leaderboard — shareable breakdown, 2x PNG poster export, trainer cards & Kanto journey replay.
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const finite = v => typeof v === 'number' && Number.isFinite(v) && v >= 0;
const fmtNum = v => finite(v) ? v.toLocaleString('en-US') : '—';
const textVal = v => v == null || v === '' ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v);
const isLocal = run => String(run.provider || '').toLowerCase().includes('ollama');
const isWon = run => run.furthest_index === 9;
const categoryOf = run => run.category === 'rvb' ? 'rvb' : 'tab';
const categoryNames = { tab: 'TAB · Tool Assisted', rvb: 'RVB · Raw Vision + Buttons' };
const categoryShort = { tab: 'TAB', rvb: 'RVB' };
const categoryExplain = {
  tab: 'TAB = RAM state as text + button menu.',
  rvb: 'RVB = raw Game Boy screenshots + button presses only.'
};
const VIA_LABELS = { deepseek: 'direct', openrouter: 'OpenRouter', 'azure-foundry': 'Azure', chatgpt: 'ChatGPT', ollama: 'Ollama' };

const ICO_ARROW = '<svg class="ico-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="7" y1="17" x2="17" y2="7"/><polyline points="7 7 17 7 17 17"/></svg>';
const ICO_FLIP = '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>';
const ICO_BACK = '<svg class="ico-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/></svg>';
const ICO_CHEV = '<svg class="ico-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>';
const ICO_BADGE = '<svg class="ico" viewBox="0 0 32 32" aria-hidden="true"><use href="#art-badge"/></svg>';
const ICO_PIN = '<svg class="ico-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>';
const ICO_DOWN = '<svg class="ico-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg>';
const ICO_RIGHT = '<svg class="ico-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>';

const priceText = run => isLocal(run) ? 'FREE'
  : finite(run.cost_usd) ? '$' + run.cost_usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: run.cost_usd > 0 && run.cost_usd < 0.01 ? 6 : 2 }) : '—';
const estMark = run => run.billing_mode === 'subscription' && finite(run.cost_usd) && !isLocal(run)
  ? '<abbr class="est" title="API-equivalent: this run used a subscription and was not billed per token">≈</abbr>' : '';
const estPlain = run => run.billing_mode === 'subscription' && finite(run.cost_usd) && !isLocal(run) ? '≈' : '';
const tokensTotal = run => finite(run.tokens_in) && finite(run.tokens_out) ? run.tokens_in + run.tokens_out : null;
const playTime = run => finite(run.active_time_s) ? run.active_time_s : run.wall_time_s;
const fmtTime = seconds => {
  if (!finite(seconds)) return '—';
  const s = Math.round(seconds), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
  return h ? `${h}h ${m}m` : m ? `${m}m ${s % 60}s` : `${s}s`;
};
const reduced = matchMedia('(prefers-reduced-motion: reduce)');

function jacketColor(run) {
  if (isLocal(run)) return '#3f8f52';
  const p = String(run.provider || '').toLowerCase();
  const f = String(run.family || '').toLowerCase();
  if (p.includes('openai') || p.includes('chatgpt') || f.includes('gpt')) return '#1f8f86';
  if (p.includes('anthropic') || f.includes('claude')) return '#c1694a';
  if (p.includes('google') || f.includes('gemini')) return '#3b82c4';
  if (p.includes('xai') || f.includes('grok')) return '#2b3947';
  return '#c99b23';
}
function shadeHex(hex, amt) {
  const n = parseInt(hex.slice(1), 16), r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  const adj = v => Math.max(0, Math.min(255, Math.round(v + amt)));
  return '#' + [adj(r), adj(g), adj(b)].map(v => v.toString(16).padStart(2, '0')).join('');
}
function trainerSvg(run, cls = 't-sprite') {
  const cap = jacketColor(run), sleeve = shadeHex(cap, -28);
  return `<svg class="${cls}" viewBox="0 0 32 48" aria-hidden="true">`
    + `<path d="M5 41h25v5H5z" fill="#122b3c44"/>`
    + `<path d="M8 4h16v4h5v9H4V9h4z" fill="${cap}"/>`
    + `<path d="M9 5h11v4H9z" fill="#ffd2a0"/>`
    + `<path d="M9 17h17v12H9z" fill="#edc18e"/>`
    + `<path d="M7 18h6v9H7z" fill="#334b47"/>`
    + `<path d="M7 29h18v11H7z" fill="#d7d9b4"/>`
    + `<path d="M5 30h6v9H5zM23 30h5v9h-5z" fill="${sleeve}"/>`
    + `<path d="M9 40h6v6H9zM20 40h6v6h-6z" fill="#243e50"/>`
    + `</svg>`;
}

const milestoneList = [
  { key: 'left_house', label: 'Left the house', short: 'Left house', tick: 'House' },
  { key: 'got_starter', label: 'Got a starter', short: 'Starter', tick: 'Starter' },
  { key: 'route_1', label: 'Reached Route 1', short: 'Route 1', tick: 'Route 1' },
  { key: 'viridian_city', label: 'Reached Viridian City', short: 'Viridian', tick: 'Viridian' },
  { key: 'got_parcel', label: "Got Oak's Parcel", short: 'Parcel', tick: 'Parcel' },
  { key: 'got_pokedex', label: 'Got the Pokédex', short: 'Pokédex', tick: 'Pokédex' },
  { key: 'viridian_forest', label: 'Entered Viridian Forest', short: 'Forest', tick: 'Forest' },
  { key: 'pewter_city', label: 'Reached Pewter City', short: 'Pewter', tick: 'Pewter' },
  { key: 'pewter_gym', label: "Entered Brock's Gym", short: "Brock's gym", tick: 'Gym' },
  { key: 'beat_brock', label: 'Beat Brock (Boulder Badge)', short: 'Beat Brock', tick: 'Badge' }
];
const modelName = run => textVal(run.display_name || run.model);
const milestoneLabel = run => milestoneList[run.furthest_index]?.label || 'No milestone reached';
const stopLabel = run => milestoneList[run.furthest_index]?.short || 'No milestone';
const trophySvg = '<svg class="trophy" viewBox="0 0 32 37" aria-hidden="true"><use href="#art-trophy"/></svg>';

function runTimestamp(run) {
  const raw = run.timestamp;
  if (typeof raw === 'string' && /^\d{8}_\d{6}$/.test(raw)) {
    return Date.UTC(+raw.slice(0,4), +raw.slice(4,6)-1, +raw.slice(6,8), +raw.slice(9,11), +raw.slice(11,13), +raw.slice(13,15));
  }
  if (finite(raw)) return raw < 1e12 ? raw * 1000 : raw;
  const parsed = Date.parse(raw || run.run_date || '');
  return Number.isFinite(parsed) ? parsed : -Infinity;
}
function runDay(run) {
  const date = String(run.run_date || '');
  if (/^\d{4}-\d{2}-\d{2}$/.test(date) && Number.isFinite(Date.parse(date))) return date;
  const ts = runTimestamp(run);
  return Number.isFinite(ts) ? new Date(ts).toISOString().slice(0, 10) : '';
}
const formatDay = day => day ? new Date(day + 'T12:00:00Z').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }) : 'Date not reported';

const furthestTurn = run => {
  if (run.furthest_index < 0) return Infinity;
  const m = (run.milestones || []).find(x => x && x.key === run.furthest_key);
  return m && finite(m.turn) ? m.turn : Infinity;
};
const rankSort = (a, b) => b.furthest_index - a.furthest_index || furthestTurn(a) - furthestTurn(b) || String(a.model).localeCompare(String(b.model));

function computeRankMeta(ranked) {
  const meta = new Map();
  let lastKey = null, lastRank = 1;
  const keyCounts = new Map();
  const keys = ranked.map(r => `${r.furthest_index}:${isWon(r) ? r.turns_used : furthestTurn(r)}`);
  keys.forEach(k => keyCounts.set(k, (keyCounts.get(k) || 0) + 1));
  ranked.forEach((r, idx) => {
    const k = keys[idx];
    const rankNum = k === lastKey ? lastRank : idx + 1;
    lastKey = k; lastRank = rankNum;
    const tied = keyCounts.get(k) > 1;
    meta.set(r, { rank: rankNum, tied, label: tied ? `=${rankNum}` : String(rankNum) });
  });
  return meta;
}

function videoURL(run) {
  if (typeof run.youtube_url !== 'string' || !run.youtube_url.trim()) return null;
  try { const u = new URL(run.youtube_url); return ['https:', 'http:'].includes(u.protocol) ? u.href : null; } catch { return null; }
}

const initParams = new URLSearchParams(location.search);
const state = {
  runs: [],
  category: initParams.get('category') === 'rvb' ? 'rvb' : 'tab',
  chartView: initParams.get('view') === 'winners' ? 'winners' : 'full',
  filter: 'all',
  stop: 'all',
  query: '',
  live: false
};

const inCategory = () => state.runs.filter(r => categoryOf(r) === state.category);

function syncUrl() {
  try {
    const url = new URL(location.href);
    if (state.category === 'rvb') url.searchParams.set('category', 'rvb'); else url.searchParams.delete('category');
    if (state.chartView === 'winners') url.searchParams.set('view', 'winners'); else url.searchParams.delete('view');
    history.replaceState(null, '', url);
  } catch { /* ignore history errors */ }
}

/* ---- Journey replay modal ---- */
let lastFocused = null;
const tile = (id,x,y,w,h,extra='') => `<use href="#art-${id}" x="${x}" y="${y}" width="${w}" height="${h}" ${extra}/>`;
const trees = (list,id='pine') => list.map(([x,y,s=1]) => tile(id,x,y,100*s,130*s)).join('');
const grass = (x,y,cols,rows,color='#577955') => `<g color="${color}">${Array.from({length:cols*rows},(_,i)=>tile('grass',x+(i%cols)*41,y+Math.floor(i/cols)*29,38,23)).join('')}</g>`;
const mapPoints = [[42,251],[97,251],[162,220],[181,161],[226,161],[125,277],[325,130],[248,61],[104,70],[63,70]];
const mapStart = [24,276];
const mapLegs = [
  [mapStart,mapPoints[0]], [mapPoints[0],[72,265],mapPoints[1]],
  [mapPoints[1],[145,251],mapPoints[2]], [mapPoints[2],[162,177],mapPoints[3]],
  [mapPoints[3],mapPoints[4]],
  [mapPoints[4],mapPoints[3],[162,177],mapPoints[2],[145,251],mapPoints[5]],
  [mapPoints[5],[145,251],mapPoints[2],[162,177],mapPoints[3],mapPoints[4],[275,161],[299,173],[325,173],mapPoints[6]],
  [mapPoints[6],[325,89],[298,61],mapPoints[7]],
  [mapPoints[7],[172,61],[141,70],mapPoints[8]], [mapPoints[8],mapPoints[9]]
];
const lineLength = pts => pts.slice(1).reduce((s,p,i) => s + Math.hypot(p[0]-pts[i][0],p[1]-pts[i][1]), 0);
const linePath = pts => pts.map(([x,y],i) => `${i ? 'L' : 'M'}${x} ${y}`).join(' ');
function linePart(pts, frac) {
  let rem = lineLength(pts) * Math.max(0, Math.min(1, frac));
  const part = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i-1], b = pts[i], len = Math.hypot(b[0]-a[0], b[1]-a[1]);
    if (rem < len) { part.push([a[0]+(b[0]-a[0])*rem/len, a[1]+(b[1]-a[1])*rem/len]); break; }
    part.push(b); rem -= len;
  }
  return part;
}
function ladder(run) {
  const turns = milestoneList.map(m => {
    const recs = run.milestones.filter(item => item.key === m.key && finite(item.turn));
    return recs.length ? Math.min(...recs.map(item => item.turn)) : null;
  });
  return milestoneList.map((m, i) => {
    const turn = turns[i], prev = i ? turns[i-1] : 0;
    return { ...m, turn, reached: finite(turn) || i <= run.furthest_index,
      delta: finite(turn) && finite(prev) && turn >= prev ? turn - prev : null };
  });
}
function facts(entries) {
  return `<dl class="provenance">${entries.map(([k,v]) => `<dt>${esc(k)}</dt><dd>${esc(textVal(v))}</dd>`).join('')}</dl>`;
}
function inspectBtn(run) {
  const url = videoURL(run);
  if (url) return `<a class="modal-btn primary" href="${esc(url)}" target="_blank" rel="noopener noreferrer" aria-label="Watch run VOD: ${esc(modelName(run))}">Watch full VOD ${ICO_ARROW}</a>`;
  return `<button type="button" class="modal-btn primary" disabled title="No VOD attached">No VOD attached</button>`;
}
function modalStats(run) {
  const costMissing = !isLocal(run) && !finite(run.cost_usd);
  return `<dl class="stats">
    <div><dt>TURNS</dt><dd>${fmtNum(run.turns_used)}<small> / ${fmtNum(run.budget_turns)}</small></dd></div>
    <div><dt>TOKENS · IN + OUT</dt><dd>${fmtNum(tokensTotal(run))}</dd></div>
    <div><dt>COST</dt><dd class="${isLocal(run) ? 'free' : ''}" ${costMissing ? 'title="Pricing unavailable / unmetered"' : ''}>${estMark(run)}${priceText(run)}</dd></div>
    <div><dt>TIME</dt><dd>${fmtTime(playTime(run))}</dd></div>
  </dl>`;
}
function runMap(run, rungs) {
  const pins = mapPoints.map(([x,y], i) => {
    const r = rungs[i], label = `${r.label} · ${finite(r.turn) ? 'turn ' + fmtNum(r.turn) : r.reached ? 'turn ?' : 'not reached'}`;
    return `<button type="button" class="map-pin ${r.reached ? '' : 'unreached'} ${r.reached && !finite(r.turn) ? 'unknown' : ''} ${x > 280 ? 'sign-left' : x < 130 ? 'sign-right' : ''}" style="--x:${x/4}%;--y:${y/3}%" data-pin="${i}" aria-label="${esc(label)}"><span aria-hidden="true">${i+1}</span><span class="pin-sign" aria-hidden="true">${esc(label)}</span></button>`;
  }).join('');
  const roads = linePath(mapLegs.flat());
  return `<div class="replay-map" role="group" aria-label="Journey map for ${esc(modelName(run))}">
    <svg class="run-map" viewBox="0 0 400 300" aria-hidden="true"><rect width="400" height="300" fill="#cedfb0"/>
    <path d="M362 0h38v300h-40v-30h15V181h-13zM0 288h84v12H0z" fill="#81c9b1"/>
    <path d="M277 91h78v102h-89v-52h11z" fill="#80a66e"/>
    ${trees([[280,69,.3],[310,58,.3],[343,61,.32],[268,107,.32],[344,108,.35],[277,135,.28],[342,153,.32],[260,183,.3]])}
    ${tile('roundtree',8,112,37,41)}${tile('roundtree',53,167,31,34)}${tile('rock',160,19,32,23)}${grass(192,232,2,2)}
    <path d="${roads}" fill="none" stroke="#849e6c" stroke-width="14" stroke-linejoin="round"/>
    <path d="${roads}" fill="none" stroke="#f2dfac" stroke-width="9" stroke-linejoin="round"/>
    ${tile('house',10,212,58,48)}${tile('house',89,226,59,49)}${tile('house',159,116,53,44)}${tile('house',205,116,53,44)}${tile('house',232,12,57,48)}${tile('gym',34,5,86,66)}
    <g class="map-place-names"><text x="13" y="205">PALLET TOWN</text><text x="139" y="296">LAB</text><text x="172" y="204">ROUTE 1</text><text x="158" y="109">VIRIDIAN CITY</text><text x="296" y="222">ROUTE 2</text><text x="296" y="236">FOREST</text><text x="215" y="85">PEWTER CITY</text><text x="25" y="91">BROCK'S GYM</text></g>
    <path class="replay-trail" d="M${mapStart.join(' ')}"/>
    <g class="replay-skulls"></g><g class="replay-trainer" transform="translate(${mapStart.join(' ')})">${tile('trainer',-8,-24,16,24)}</g>
    <g class="replay-finish" visibility="hidden"></g></svg>${pins}<div class="blackout-overlay" aria-hidden="true"></div></div>
    <p class="map-caption">1-10: ladder order · teal = recorded · gold = replayed · ${isWon(run) ? 'trophy = beat Brock' : 'red X = stop'} · skull = faint</p>`;
}
function runDetails(run, rungs) {
  const largest = Math.max(-1, ...rungs.map(r => r.delta ?? -1));
  const hardest = largest > 0 ? rungs.findIndex(r => r.delta === largest) : -1;
  return `<div class="run-details"><div class="ladder-heading"><b>THE LADDER</b><span>FIRST HIT / SEGMENT TURNS</span></div>
    <ol class="receipt-list">${rungs.map((r, i) => `<li data-rung="${i}" class="${r.reached ? 'pending' : 'unreached'} ${r.reached && !finite(r.turn) ? 'unknown' : ''} ${i === hardest ? 'hardest' : ''}"><span class="rung-number">${i+1}</span><span>${esc(r.short)}${i === hardest ? '<em>slowest segment</em>' : ''}</span><span class="receipt-turn">${finite(r.turn) ? fmtNum(r.turn) : r.reached ? '?' : '—'}</span><span class="receipt-delta">${finite(r.delta) ? '+' + fmtNum(r.delta) : r.reached ? '?' : '—'}</span></li>`).join('')}</ol>
    <p class="receipt-note">? = unknown receipt · — = unreached. Segment = turns since the previous rung.</p>
    ${facts([['Run ID', run.run_id], ['Category', categoryNames[categoryOf(run)]], ['Think', run.think_level], ['Context', finite(run.num_ctx) ? fmtNum(run.num_ctx) : null],
      ['Parameters', run.model_params], ['Quant', run.quant], ['Tokens in', fmtNum(run.tokens_in)], ['Tokens out', fmtNum(run.tokens_out)],
      ['Prompt', run.prompt_version], ['Route', run.execution_route], ['Run date', formatDay(runDay(run))]])}</div>`;
}
const PULSE_MS = 1100, BURST_AT = 0.25;
function modalCardMarkup(run) {
  const rungs = ladder(run);
  const hits = rungs.filter(r => finite(r.turn) && r.turn <= run.turns_used).length;
  return `<article class="run-card ${isWon(run) ? 'is-winner' : ''}" data-run="${run.uid}">
    <div class="card-inner">
      <div class="card-face card-front" aria-hidden="false">
        <div class="card-body">
          <div class="modal-head-row">
            <div>
              <h3 class="model-name" id="modal-model-name">${esc(modelName(run))}</h3>
              <p class="provider">${esc(textVal(run.provider))}${run.run_name ? ' / ' + esc(run.run_name) : ''}</p>
              ${run.in_game_name ? `<p class="ingame-name">plays as <b class="player-name">${esc(run.in_game_name)}</b>${run.rival_name ? ` · rival <b class="rival-name">${esc(run.rival_name)}</b>` : ''}</p>` : ''}
            </div>
            ${trainerSvg(run, 't-sprite')}
          </div>
          <div class="card-tags">
            ${categoryOf(run) === 'rvb' ? '<span class="tag rvb">RVB</span>' : ''}
            <span class="tag ${isLocal(run) ? 'local' : 'api'}">${isLocal(run) ? 'LOCAL' : 'API'}</span>
            <span class="tag">${esc(textVal(run.family))}</span>
            <span class="tag">GEN 1 · RED</span>
          </div>
          <p class="furthest"><b>${Math.max(0, run.furthest_index + 1)}/10</b> ${esc(milestoneLabel(run))}</p>
          ${modalStats(run)}
          ${facts([['Prompt', run.prompt_version], ['Route', run.execution_route], ['Run date', formatDay(runDay(run))]])}
          ${run.caveat ? `<p class="run-caveat"><b>CAVEAT</b> ${esc(run.caveat)}</p>` : ''}
          <div class="modal-actions">
            ${inspectBtn(run)}
            <button type="button" class="modal-btn secondary" data-replay="flip">${ICO_FLIP} Flip for 10-rung replay</button>
          </div>
        </div>
      </div>
      <div class="card-face card-back" aria-hidden="true" inert>
        <div class="replay-heading"><h3>${esc(modelName(run))} · Journey</h3><button type="button" class="text-button" data-replay="flip">${ICO_BACK} Front</button></div>
        <div class="replay-toolbar">
          <div class="replay-controls" role="group" aria-label="Journey replay controls">
            <button type="button" data-replay="play">Play</button>
            <button type="button" data-replay="restart">Restart</button>
            <button type="button" data-replay="end">Skip to end</button>
            <span class="replay-status">Ready · ~${Math.round(6 + hits * PULSE_MS / 1000)}s</span>
          </div>
          <progress class="replay-progress" max="${run.turns_used || 1}" value="0" aria-label="Replay progress"></progress>
        </div>
        ${runMap(run, rungs)}
        <div class="replay-body">
          <p class="running-label">RUNNING TOTALS <span>· tokens, cost &amp; time interpolated</span></p>
          <dl class="stats replay-stats">
            <div><dt>TURNS</dt><dd><span class="counter-stage"><span data-counter="turns">0</span><span class="sparkles" aria-hidden="true"></span></span><small> / ${fmtNum(run.turns_used)}</small></dd></div>
            <div><dt>TOKENS · IN + OUT</dt><dd data-counter="tokens">${finite(tokensTotal(run)) ? '0' : '—'}</dd></div>
            <div><dt>COST</dt><dd>${estMark(run)}<span data-counter="cost">${priceText({...run, cost_usd: finite(run.cost_usd) ? 0 : null})}</span></dd></div>
            <div><dt>TIME</dt><dd data-counter="time">${finite(playTime(run)) ? '0s' : '—'}</dd></div>
          </dl>
          ${runDetails(run, rungs)}
        </div>
      </div>
    </div>
  </article>`;
}

const replays = new WeakMap();
let activeReplay = null;
function replayTimeline(run, rungs) {
  const arrivals = [0]; let lastKnown = 0;
  for (let i = 0; i <= run.furthest_index; i++) {
    const t = rungs[i].turn;
    const ok = finite(t) && t >= lastKnown && t <= run.turns_used;
    arrivals.push(ok ? t : null);
    if (ok) lastKnown = t;
  }
  arrivals.push(run.turns_used);
  for (let l = 0; l < arrivals.length - 1;) {
    let r = l + 1; while (arrivals[r] === null) r++;
    for (let i = l + 1; i < r; i++) arrivals[i] = arrivals[l] + (arrivals[r] - arrivals[l]) * (i - l) / (r - l);
    l = r;
  }
  const segments = arrivals.slice(1).map((end, i) => {
    const tail = i > run.furthest_index;
    const stop = mapPoints[run.furthest_index] || mapStart;
    const pts = tail ? !isWon(run) && end > arrivals[i] ? linePart(mapLegs[i], 0.55) : [stop, stop] : mapLegs[i];
    const known = tail ? run.furthest_index < 0 || finite(rungs[i-1].turn) : finite(rungs[i].delta);
    return { start: arrivals[i], end, points: pts, weight: known ? end - arrivals[i] : run.turns_used / (arrivals.length - 1), duration: 0 };
  });
  let rem = 6000, open = segments.filter(s => s.end > s.start);
  while (open.length) {
    const w = open.reduce((s, x) => s + x.weight, 0);
    const short = open.filter(s => rem * s.weight / w < 250);
    if (!short.length) { open.forEach(s => { s.duration = rem * s.weight / w; }); break; }
    short.forEach(s => { s.duration = 250; rem -= 250; });
    open = open.filter(s => !short.includes(s));
  }
  let el = 0; segments.forEach(s => { s.at = el; el += s.duration; });
  return { segments, duration: el };
}
function getReplay(cardEl) {
  if (replays.has(cardEl)) return replays.get(cardEl);
  const run = state.runs.find(r => r.uid === cardEl.dataset.run), rungs = ladder(run);
  const timeline = replayTimeline(run, rungs);
  const faints = (Array.isArray(run.blackouts) ? run.blackouts : []).filter(t => finite(t) && t <= run.turns_used).sort((a,b) => a-b).map(turn => {
    let pin = rungs.findIndex(r => finite(r.turn) && r.turn > turn);
    if (pin < 0) pin = Math.min(9, Math.max(0, run.furthest_index + 1));
    return { turn, pin, at: null };
  });
  const replay = {
    card: cardEl, run, rungs, ...timeline, faints, turn: -1, elapsed: 0, hold: 0, burstTimer: 0, lastFrame: null, frame: 0, playing: false,
    events: [...new Set([...rungs.map(r => r.turn).filter(t => finite(t) && t <= run.turns_used), ...faints.map(f => f.turn), run.turns_used])].sort((a,b) => a-b),
    pins: [...cardEl.querySelectorAll('[data-pin]')], rows: [...cardEl.querySelectorAll('[data-rung]')],
    counters: Object.fromEntries([...cardEl.querySelectorAll('[data-counter]')].map(el => [el.dataset.counter, el])),
    sparks: cardEl.querySelector('.sparkles'), total: cardEl.querySelector('.replay-stats small'),
    sprite: cardEl.querySelector('.replay-trainer'), trail: cardEl.querySelector('.replay-trail'), finish: cardEl.querySelector('.replay-finish'),
    overlay: cardEl.querySelector('.blackout-overlay'), progress: cardEl.querySelector('.replay-progress'),
    play: cardEl.querySelector('[data-replay="play"]'), status: cardEl.querySelector('.replay-status')
  };
  cardEl.querySelector('.replay-skulls').innerHTML = faints.map((f, i) => {
    const [x, y] = mapPoints[f.pin];
    return `<g data-faint="${i}" visibility="hidden" transform="translate(${x+13+(i%3)*7} ${y-38-Math.floor(i/3)*11})"><title>Fainted at turn ${fmtNum(f.turn)} · heading to ${esc(rungs[f.pin].label)}</title><path d="M3 0h10v2h3v10h-3v5H3v-5H0V2h3z" fill="#f8f7eb" stroke="#101c20" stroke-width="2"/><path d="M3 5h4v4H3zM10 5h4v4h-4zM7 10h3v3H7zM5 14h2v3H5zM10 14h2v3h-2z" fill="#101c20"/></g>`;
  }).join('');
  replay.skulls = [...cardEl.querySelectorAll('[data-faint]')];
  replay.finish.innerHTML = isWon(run) ? '<g transform="translate(-10 -32) scale(.65)"><use href="#art-trophy"/></g>' : '<path d="M-6-13l12 12m0-12L-6-1" stroke="#a52f24" stroke-width="4"/>';
  replays.set(cardEl, replay);
  drawReplay(replay, 0, true);
  return replay;
}
function pulseTurns(replay) {
  const el = replay.counters.turns;
  replay.hold = PULSE_MS;
  el.getAnimations().forEach(a => a.cancel());
  el.animate([
    { transform: 'scale(1)', color: 'var(--ink)', textShadow: '0 0 0 transparent' },
    { transform: 'scale(1.45)', color: '#9c6c04', textShadow: '0 0 12px var(--gold-soft)', offset: BURST_AT, easing: 'ease-out' },
    { transform: 'scale(1.45)', color: '#9c6c04', textShadow: '0 0 8px var(--gold-soft)', offset: 0.75 },
    { transform: 'scale(1)', color: 'var(--ink)', textShadow: '0 0 0 transparent' }
  ], { duration: PULSE_MS, easing: 'ease-in-out' });
  if (replay.total) {
    replay.total.getAnimations().forEach(a => a.cancel());
    replay.total.animate([{ opacity: 1 }, { opacity: 0.14, offset: BURST_AT }, { opacity: 0.14, offset: 0.75 }, { opacity: 1 }], { duration: PULSE_MS });
  }
  clearTimeout(replay.burstTimer);
  replay.burstTimer = setTimeout(() => burstSparkles(replay), PULSE_MS * BURST_AT);
}
function burstSparkles(replay) {
  if (!replay.sparks || !replay.card.isConnected) return;
  const count = 16;
  for (let i = 0; i < count; i++) {
    const spark = document.createElement('i');
    spark.className = 'spark';
    replay.sparks.appendChild(spark);
    const angle = (i / count) * Math.PI * 2 + (Math.random() - 0.5) * 0.6, dist = 28 + Math.random() * 36;
    spark.animate([
      { transform: 'translate(-50%,-50%) rotate(0deg) scale(1)', opacity: 1 },
      { opacity: 1, offset: 0.55 },
      { transform: `translate(calc(-50% + ${(Math.cos(angle) * dist).toFixed(1)}px),calc(-50% + ${(Math.sin(angle) * dist - 8).toFixed(1)}px)) rotate(${Math.round(180 + Math.random() * 270)}deg) scale(.4)`, opacity: 0 }
    ], { duration: 650 + Math.random() * 320, easing: 'cubic-bezier(.1,.8,.3,1)' }).finished.then(() => spark.remove(), () => spark.remove());
  }
}
function clearCelebration(replay) {
  clearTimeout(replay.burstTimer);
  replay.hold = 0;
  [replay.counters.turns, replay.total].filter(Boolean).forEach(el => el.getAnimations().forEach(a => a.cancel()));
  if (replay.sparks) replay.sparks.replaceChildren();
}
function drawReplay(replay, turn, instant = false) {
  const { run, rungs, segments, counters } = replay, before = replay.turn;
  replay.turn = turn;
  const ratio = run.turns_used ? turn / run.turns_used : 1;
  let walked = [mapStart];
  for (const seg of segments) {
    if (turn < seg.start) break;
    const f = seg.end > seg.start ? (turn - seg.start) / (seg.end - seg.start) : 1;
    walked = walked.concat(linePart(seg.points, f).slice(1));
    if (f < 1) break;
  }
  const [x, y] = walked[walked.length - 1];
  replay.sprite.setAttribute('transform', `translate(${x} ${y})`);
  replay.trail.setAttribute('d', linePath(walked));
  replay.finish.setAttribute('visibility', turn >= run.turns_used ? 'visible' : 'hidden');
  replay.finish.setAttribute('transform', `translate(${x} ${y})`);
  replay.sprite.setAttribute('visibility', turn >= run.turns_used ? 'hidden' : 'visible');
  let celebrate = false;
  rungs.forEach((r, i) => {
    const hit = finite(r.turn) && r.turn <= turn;
    replay.pins[i].classList.toggle('is-hit', hit);
    replay.rows[i].classList.toggle('is-hit', hit);
    if (hit && r.turn > before && !instant && !reduced.matches) celebrate = true;
  });
  counters.turns.textContent = fmtNum(Math.floor(turn));
  if (celebrate) pulseTurns(replay);
  counters.tokens.textContent = fmtNum(finite(tokensTotal(run)) ? Math.round(tokensTotal(run) * ratio) : null);
  counters.cost.textContent = priceText({ ...run, cost_usd: finite(run.cost_usd) ? run.cost_usd * ratio : null });
  counters.time.textContent = fmtTime(finite(playTime(run)) ? playTime(run) * ratio : null);
  replay.progress.value = run.turns_used ? turn : 1;
  let dark = 0;
  replay.faints.forEach((f, i) => {
    if (f.turn <= turn && f.at === null) f.at = instant ? -Infinity : replay.elapsed;
    const age = f.at === null ? -1 : replay.elapsed - f.at;
    replay.skulls[i].setAttribute('visibility', age >= 400 ? 'visible' : 'hidden');
    if (age >= 0 && age < 400) dark = Math.max(dark, Math.min(1, age / 100, (400 - age) / 100));
  });
  replay.overlay.style.opacity = dark;
}
function replayControls(replay) {
  replay.play.textContent = replay.playing ? 'Pause' : replay.turn >= replay.run.turns_used ? 'Replay' : 'Play';
  replay.status.textContent = reduced.matches ? 'End · motion reduced' : replay.playing ? 'Playing' : replay.turn >= replay.run.turns_used ? 'Complete' : 'Paused';
  replay.card.classList.toggle('replay-playing', replay.playing);
}
function pauseReplay(replay = activeReplay) {
  if (!replay) return;
  cancelAnimationFrame(replay.frame);
  replay.playing = false; replay.lastFrame = null;
  if (activeReplay === replay) activeReplay = null;
  replayControls(replay);
}
function endReplay(replay) {
  pauseReplay(replay); clearCelebration(replay); replay.elapsed = replay.duration + 400;
  replay.faints.forEach(f => { f.at = -Infinity; });
  drawReplay(replay, replay.run.turns_used, true); replayControls(replay);
}
function tickReplay(replay, now) {
  if (!replay.playing) return;
  if (!replay.card.isConnected || document.hidden) { pauseReplay(replay); return; }
  const dt = replay.lastFrame === null ? 0 : now - replay.lastFrame;
  replay.lastFrame = now;
  if (replay.hold > 0) { replay.hold = Math.max(0, replay.hold - dt); replay.frame = requestAnimationFrame(n => tickReplay(replay, n)); return; }
  replay.elapsed += dt;
  const seg = replay.segments.find(s => s.duration && replay.elapsed < s.at + s.duration);
  const target = seg ? seg.start + (seg.end - seg.start) * Math.max(0, (replay.elapsed - seg.at) / seg.duration) : replay.run.turns_used;
  const crossing = replay.events.find(t => t > replay.turn && t <= target);
  drawReplay(replay, crossing ?? target);
  if (replay.turn >= replay.run.turns_used && replay.hold <= 0 && replay.faints.every(f => f.at !== null && replay.elapsed - f.at >= 400)) { pauseReplay(replay); return; }
  replay.frame = requestAnimationFrame(n => tickReplay(replay, n));
}
function playReplay(replay, restart = false) {
  pauseReplay();
  if (reduced.matches) { endReplay(replay); return; }
  if (restart || replay.turn >= replay.run.turns_used) {
    clearCelebration(replay); replay.elapsed = 0; replay.turn = -1;
    replay.faints.forEach(f => { f.at = null; });
    drawReplay(replay, 0, true);
  }
  replay.faints.filter(f => f.turn === 0 && f.at === -Infinity).forEach(f => { f.at = 0; });
  activeReplay = replay; replay.playing = true; replay.lastFrame = null;
  replayControls(replay);
  replay.frame = requestAnimationFrame(n => tickReplay(replay, n));
}
function flipCard(cardEl) {
  const back = !cardEl.classList.contains('is-flipped');
  cardEl.classList.toggle('is-flipped', back);
  ['front', 'back'].forEach(face => {
    const el = cardEl.querySelector('.card-' + face), vis = (face === 'back') === back;
    el.inert = !vis; el.setAttribute('aria-hidden', String(!vis));
  });
  $('modal-content').scrollTop = 0;
  if (back) {
    playReplay(getReplay(cardEl));
    const playBtn = cardEl.querySelector('[data-replay="play"]');
    if (playBtn) playBtn.focus();
  } else {
    pauseReplay(replays.get(cardEl));
    const flipBtn = cardEl.querySelector('.card-front [data-replay="flip"]');
    if (flipBtn) flipBtn.focus();
  }
}
function openModal(run, triggerEl) {
  lastFocused = triggerEl || document.activeElement;
  const peers = [...state.runs.filter(other => categoryOf(other) === categoryOf(run))].sort(rankSort);
  const rankInfo = computeRankMeta(peers).get(run) || { label: '?' };
  const chrome = $('modal-chrome');
  chrome.classList.toggle('is-winner', isWon(run));
  $('modal-ribbon-text').innerHTML = `${isWon(run) ? trophySvg + 'BADGE EARNED' : 'RAN OUT OF TURNS'} · #${rankInfo.label} (${categoryShort[categoryOf(run)]})`;
  $('modal-content').innerHTML = modalCardMarkup(run);
  $('modal-content').scrollTop = 0;
  $('run-modal').showModal();
  const focusBtn = $('modal-content').querySelector('.card-front [data-replay="flip"]');
  if (focusBtn) focusBtn.focus();
}

/* ---- Board Data & Rendering ---- */
function computeBoardData() {
  const ranked = [...inCategory()].sort(rankSort);
  const rankMeta = computeRankMeta(ranked);
  const winners = ranked.filter(isWon);
  const short = ranked.filter(r => !isWon(r));
  const nameCounts = ranked.reduce((m, r) => {
    const n = modelName(r);
    m[n] = (m[n] || 0) + 1;
    return m;
  }, {});
  const latestDay = ranked.map(runDay).filter(Boolean).sort().pop() || '';
  const fastest = winners[0] || null;
  const pricedWins = winners.filter(r => !isLocal(r) && finite(r.cost_usd) && r.cost_usd > 0);
  const cheapest = pricedWins.length ? pricedWins.reduce((a, b) => a.cost_usd <= b.cost_usd ? a : b) : null;
  const locals = ranked.filter(isLocal);
  const bestLocal = locals[0] || null;
  const winTurns = winners.map(r => r.turns_used).sort((a, b) => a - b);
  const medianWin = winTurns.length
    ? (winTurns.length % 2 ? winTurns[(winTurns.length - 1) / 2] : Math.round((winTurns[winTurns.length / 2 - 1] + winTurns[winTurns.length / 2]) / 2))
    : null;
  const passPct = ranked.length ? Math.round((winners.length / ranked.length) * 100) : 0;
  return { ranked, rankMeta, winners, short, nameCounts, latestDay, fastest, cheapest, bestLocal, locals, medianWin, passPct };
}

function renderShareFrame(data) {
  const { ranked, rankMeta, winners, short, nameCounts, latestDay, fastest, cheapest, bestLocal, locals, medianWin, passPct } = data;
  const cat = state.category;
  const winnersOnly = state.chartView === 'winners';

  $('frame-kicker').textContent = `PokéBench · ${categoryShort[cat]} Leaderboard · ${latestDay ? formatDay(latestDay) : 'Live'}`;
  $('frame-headline').textContent = winnersOnly
    ? `${winners.length} of ${ranked.length} AIs beat Brock.`
    : `${winners.length} AIs beat Brock. ${short.length} ran out of turns.`;
  $('frame-sub').textContent = `Pokémon Red, new save: beat Brock (1st Gym) in 1,000 turns. ${categoryExplain[cat]} Scored from RAM.`;
  $('pass-badge').innerHTML = `<div class="pass-top"><span class="pass-rate">${passPct}%</span><span class="pass-lbl">beat Brock (${winners.length}/${ranked.length})</span></div><span class="pass-bar" aria-hidden="true"><i style="width:${passPct}%"></i></span>`;

  const kpiItems = winnersOnly ? [
    {
      sprite: fastest ? trainerSvg(fastest, 'kpi-sprite') : '',
      label: 'Fastest Boulder Badge',
      name: fastest ? modelName(fastest) : 'None yet',
      stat: fastest ? `${fmtNum(fastest.turns_used)} turns` : '—',
      cls: 'accent-gold'
    },
    {
      sprite: '',
      label: 'Cheapest winning run',
      name: cheapest ? modelName(cheapest) : 'None yet',
      stat: cheapest ? `${estPlain(cheapest)}${priceText(cheapest)}` : '—',
      cls: 'accent-gold'
    },
    {
      sprite: '',
      label: 'Median winning run',
      name: medianWin ? `${fmtNum(medianWin)} turns` : '—',
      stat: `${winners.length} badge winners`,
      cls: ''
    }
  ] : [
    {
      sprite: fastest ? trainerSvg(fastest, 'kpi-sprite') : '',
      label: 'Fastest Boulder Badge',
      name: fastest ? modelName(fastest) : 'None yet',
      stat: fastest ? `${fmtNum(fastest.turns_used)} turns` : '—',
      cls: 'accent-gold'
    },
    {
      sprite: '',
      label: 'Cheapest winning run',
      name: cheapest ? modelName(cheapest) : 'None yet',
      stat: cheapest ? `${estPlain(cheapest)}${priceText(cheapest)}` : '—',
      cls: 'accent-gold'
    },
    {
      sprite: '',
      label: 'Furthest local model',
      name: bestLocal ? modelName(bestLocal) : 'None yet',
      stat: bestLocal ? `${stopLabel(bestLocal)}${finite(furthestTurn(bestLocal)) ? ' · turn ' + fmtNum(furthestTurn(bestLocal)) : ''}` : '—',
      cls: 'accent-green'
    }
  ];

  $('kpi-strip').innerHTML = kpiItems.map(k =>
    `<div class="kpi">${k.sprite}<div class="kpi-body"><span class="kpi-label">${esc(k.label)}</span><div class="kpi-val"><strong>${esc(k.name)}</strong><span class="${k.cls}">${esc(k.stat)}</span></div></div></div>`
  ).join('');

  const viaTag = r => nameCounts[modelName(r)] > 1 ? `<span class="r-via">${esc(VIA_LABELS[r.provider] || r.provider || '')}</span>` : '';
  const localTag = r => isLocal(r) ? '<span class="r-local">LOCAL</span>' : '';

  const winGrid = [250, 500, 750, 1000];
  const winRowsHtml = winners.map((r, i) => {
    const rm = rankMeta.get(r);
    const pct = Math.min(100, (r.turns_used / 1000) * 100);
    const inside = pct >= 82;
    const valHtml = winnersOnly ? `${fmtNum(r.turns_used)} <small>turns</small>` : `${fmtNum(r.turns_used)}t`;
    const costHtml = winnersOnly ? `<span class="r-cost ${isLocal(r) ? 'free' : ''}">${estPlain(r)}${priceText(r)}</span>` : '';
    return `<button type="button" class="chart-row ${i === 0 ? 'is-first' : ''}" data-uid="${esc(r.uid)}" title="${esc(modelName(r))}: beat Brock in ${fmtNum(r.turns_used)} turns (${priceText(r)})" aria-label="Rank ${rm.label}, ${esc(modelName(r))}, beat Brock in ${fmtNum(r.turns_used)} turns, open details">
      <span class="r-rank">${esc(rm.label)}</span>
      <span class="r-name"><span class="r-name-text">${esc(modelName(r))}</span>${viaTag(r)}${localTag(r)}</span>
      <span class="r-plot">${winGrid.map(g => `<span class="r-grid" style="left:${g / 10}%"></span>`).join('')}<span class="r-rail"></span><span class="r-bar" style="width:${pct.toFixed(2)}%"></span><span class="r-val ${inside ? 'is-inside' : ''}" style="left:${pct.toFixed(2)}%">${valHtml}</span><span class="r-caret">${ICO_CHEV}</span></span>
      ${costHtml}
    </button>`;
  }).join('');

  const winAxisHtml = `<div class="chart-axis"><span></span><span></span><div class="axis-ticks">${[0, ...winGrid].map((g, idx, arr) =>
    `<span class="axis-tick ${idx === 0 ? 'first' : idx === arr.length - 1 ? 'last' : ''}" style="left:${g / 10}%">${g === 1000 ? '1,000' : g}</span>`).join('')}</div>${winnersOnly ? '<span></span>' : ''}</div>`;

  const rvbFiller = (!winnersOnly && short.length - winners.length >= 3)
    ? `<div class="rvb-callout"><strong>Why RVB is harder than TAB</strong>Models see only raw 160×144 Game Boy frames — no RAM map, no coordinates, no HP numbers.</div>` : '';

  const winColHtml = `<div class="chart-col win-col">
    <div class="col-head">
      <h2>${ICO_BADGE} Beat Brock <span class="col-count">${winners.length}</span></h2>
      <div class="col-head-right">
        <span class="dir-pill">${ICO_DOWN} Lower is better</span>
        ${winnersOnly ? '<span class="col-cost-hdr">Cost</span>' : ''}
      </div>
    </div>
    <div class="chart-rows">${winRowsHtml || '<div class="empty">No badge winners yet.</div>'}${rvbFiller}</div>
    ${winAxisHtml}
  </div>`;

  const stopX = idx => ((idx + 1) / milestoneList.length) * 100;
  const shortRowsHtml = short.map((r) => {
    const rm = rankMeta.get(r);
    const none = r.furthest_index < 0;
    const pct = none ? 0 : stopX(r.furthest_index);
    const ft = furthestTurn(r);
    const turnNote = finite(ft) ? ` <small>${fmtNum(ft)}t</small>` : '';
    return `<button type="button" class="chart-row" data-uid="${esc(r.uid)}" title="${esc(modelName(r))}: ${esc(milestoneLabel(r))}${finite(ft) ? ' (first reached turn ' + fmtNum(ft) + ')' : ''}" aria-label="Rank ${rm.label}, ${esc(modelName(r))}, ${esc(stopLabel(r))}, open details">
      <span class="r-rank">${esc(rm.label)}</span>
      <span class="r-name"><span class="r-name-text">${esc(modelName(r))}</span>${viaTag(r)}${localTag(r)}</span>
      <span class="r-plot">${[0, 3, 6, 8].map(s => `<span class="r-grid" style="left:${stopX(s)}%"></span>`).join('')}${none ? '' : `<span class="r-bar short" style="width:${pct.toFixed(2)}%"></span>`}<span class="r-val ${none ? 'is-none' : ''}" style="left:${pct.toFixed(2)}%">${esc(stopLabel(r))}${turnNote}</span><span class="r-caret">${ICO_CHEV}</span></span>
    </button>`;
  }).join('');

  const shortPips = milestoneList.map((_, s) => `<span class="axis-pip" style="left:${stopX(s)}%"></span>`).join('');
  const shortTicks = [[0, 'House'], [3, 'Viridian'], [6, 'Forest'], [8, 'Gym']];
  const shortAxisHtml = `<div class="chart-axis"><span></span><span></span><div class="axis-ticks">${shortPips}${shortTicks.map(([idx, lbl]) =>
    `<span class="axis-tick" style="left:${stopX(idx)}%">${lbl}</span>`).join('')}</div></div>`;

  const shortColHtml = `<div class="chart-col short-col">
    <div class="col-head"><h2>Ran out of turns <span class="col-count short">${short.length}</span></h2><span class="dir-pill short">${ICO_RIGHT} Further is better</span></div>
    <div class="chart-rows">${shortRowsHtml || '<div class="empty">Every model beat Brock.</div>'}</div>
    ${shortAxisHtml}
  </div>`;

  const gridEl = $('chart-grid');
  gridEl.classList.toggle('single', winnersOnly);
  gridEl.innerHTML = winnersOnly ? winColHtml : winColHtml + shortColHtml;

  const localWinCount = winners.filter(isLocal).length;
  $('frame-legend').innerHTML = winnersOnly
    ? `<span class="leg-item"><i class="leg-swatch win"></i>Boulder Badge (${localWinCount}/${locals.length} local)</span><span>≈ API-equiv subscription · — pricing unavailable</span><span class="frame-tagline">Billions of parameters vs. one old man.</span>`
    : `<span class="leg-item"><i class="leg-swatch win"></i>Beat Brock (budget used)</span><span class="leg-item"><i class="leg-swatch short"></i>Ran out (furthest stop + hit turn)</span><span class="frame-tagline">Billions of parameters vs. one old man.</span>`;

  $('jump-cards-text').textContent = `Browse all ${ranked.length} trainer cards`;
}

function buildFilterChrome(data) {
  const { ranked, winners, short } = data;
  const localCount = ranked.filter(isLocal).length;
  const apiCount = ranked.length - localCount;

  const filterDefs = [
    ['all', 'All', ranked.length],
    ['won', 'Beat Brock', winners.length],
    ['short', 'Ran out', short.length],
    ['local', 'Local', localCount],
    ['api', 'API', apiCount]
  ];
  $('type-filters').innerHTML = filterDefs.map(([k, lbl, n]) =>
    `<button type="button" class="fpill" data-filter="${k}" aria-pressed="${state.filter === k}">${lbl} (${n})</button>`).join('');

  const stopSel = $('stop-filter');
  const noneCnt = ranked.filter(r => r.furthest_index < 0).length;
  stopSel.innerHTML = `<option value="all">All stops (${ranked.length})</option>` +
    milestoneList.slice().reverse().map((m, revIdx) => {
      const idx = milestoneList.length - 1 - revIdx;
      const cnt = ranked.filter(r => r.furthest_index === idx).length;
      return `<option value="${idx}">${esc(m.short)} (${cnt})</option>`;
    }).join('') +
    (noneCnt ? `<option value="-1">No milestone (${noneCnt})</option>` : '');
  stopSel.value = String(state.stop);
}

function renderCardGrid(data, announce = false) {
  const { ranked, rankMeta, nameCounts } = data;

  document.querySelectorAll('#type-filters [data-filter]').forEach(btn => {
    btn.setAttribute('aria-pressed', String(btn.dataset.filter === state.filter));
  });
  $('stop-filter').value = String(state.stop);

  const q = state.query.trim().toLowerCase();
  const shown = ranked.filter(r => {
    if (state.filter === 'won' && !isWon(r)) return false;
    if (state.filter === 'short' && isWon(r)) return false;
    if (state.filter === 'local' && !isLocal(r)) return false;
    if (state.filter === 'api' && isLocal(r)) return false;
    if (state.stop !== 'all' && r.furthest_index !== Number(state.stop)) return false;
    if (q) {
      const hay = `${modelName(r)} ${r.provider || ''} ${r.family || ''} ${stopLabel(r)}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  $('cards-count').textContent = `${shown.length} of ${ranked.length} models`;
  if (announce) $('announcer').textContent = `Showing ${shown.length} of ${ranked.length} models.`;

  $('grid').innerHTML = shown.length ? shown.map(run => {
    const rm = rankMeta.get(run);
    const done = isWon(run);
    const rankCls = rm.rank === 1 ? 'r1' : rm.rank === 2 ? 'r2' : rm.rank === 3 ? 'r3' : '';
    const pips = Array.from({ length: 10 }, (_, i) => `<i class="${i <= run.furthest_index ? 'hit' : ''}"></i>`).join('');
    const via = nameCounts[modelName(run)] > 1 ? (VIA_LABELS[run.provider] || run.provider) : run.provider;
    const hasVod = Boolean(videoURL(run));
    const costMissing = !isLocal(run) && !finite(run.cost_usd);
    return `<button type="button" class="trainer ${rm.rank === 1 ? 'is-champ' : ''}" data-uid="${esc(run.uid)}" aria-label="${esc(modelName(run))}, rank ${rm.label}, ${esc(stopLabel(run))}, open run details and replay">
      <div class="body">
        <div class="top">
          <span class="t-rank ${rankCls}">${esc(rm.label)}</span>
          <div class="t-name-wrap">
            <div class="t-name">${esc(modelName(run))}</div>
            <div class="t-provider">
              <span class="t-badge ${isLocal(run) ? 'local' : 'api'}">${isLocal(run) ? 'LOCAL' : 'API'}</span>
              ${categoryOf(run) === 'rvb' ? '<span class="t-badge rvb">RVB</span>' : ''}
              <span>${esc(via || '')}</span>
            </div>
          </div>
          ${trainerSvg(run, 't-sprite')}
        </div>
        <div class="kv">
          <div><div class="kv-label">Turns</div><div class="kv-value">${fmtNum(run.turns_used)}${done ? '<small> /1k</small>' : ''}</div></div>
          <div><div class="kv-label">Run cost</div><div class="kv-value ${isLocal(run) ? 'free' : ''}" ${costMissing ? 'title="Pricing unavailable / unmetered"' : ''}>${estMark(run)}${priceText(run)}</div></div>
        </div>
        <div class="pips ${done ? 'won' : ''}" title="${Math.max(0, run.furthest_index + 1)} of 10 milestones reached" aria-hidden="true">${pips}</div>
      </div>
      <div class="foot ${done ? 'won' : ''}">
        <span class="foot-stop">${done ? ICO_BADGE : ICO_PIN}${esc(stopLabel(run))}</span>
        <span class="foot-meta">${hasVod ? '<span class="vod-pill">VOD</span>' : ''}<span>Replay</span>${ICO_CHEV}</span>
      </div>
    </button>`;
  }).join('') : `<div class="empty"><span>No trainers match this filter.</span><button type="button" class="action-btn" data-reset-filters>Reset filters</button></div>`;
}

function buildCategoryTabs() {
  const counts = {
    tab: state.runs.filter(r => categoryOf(r) === 'tab').length,
    rvb: state.runs.filter(r => categoryOf(r) === 'rvb').length
  };
  const catShortNames = { tab: 'TAB · Assisted', rvb: 'RVB · Vision' };
  $('categories').innerHTML = ['tab', 'rvb'].map(cat =>
    `<button type="button" class="seg-btn" data-category="${cat}" aria-pressed="${state.category === cat}"><span class="seg-full-lbl">${categoryNames[cat]}</span><span class="seg-short-lbl">${catShortNames[cat]}</span> <span class="seg-count">(${counts[cat]})</span></button>`).join('');
}

function syncCategoryAndViewState() {
  document.querySelectorAll('#categories [data-category]').forEach(btn => {
    btn.setAttribute('aria-pressed', String(btn.dataset.category === state.category));
  });
  document.querySelectorAll('#chart-mode [data-view]').forEach(btn => {
    btn.setAttribute('aria-pressed', String(btn.dataset.view === state.chartView));
  });
}

let cachedBoardData = null;
function renderAll(rebuildFilters = true) {
  syncCategoryAndViewState();
  cachedBoardData = computeBoardData();
  renderShareFrame(cachedBoardData);
  if (rebuildFilters) buildFilterChrome(cachedBoardData);
  renderCardGrid(cachedBoardData, false);
}

/* ---- Crisp 2x Retina Phone-Readable Social Poster PNG Exporter ---- */
function roundRectPath(ctx, x, y, w, h, r) {
  const rad = typeof r === 'number' ? [r, r, r, r] : r;
  const [tl, tr, br, bl] = rad;
  ctx.beginPath();
  ctx.moveTo(x + tl, y);
  ctx.lineTo(x + w - tr, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + tr);
  ctx.lineTo(x + w, y + h - br);
  ctx.quadraticCurveTo(x + w, y + h, x + w - br, y + h);
  ctx.lineTo(x + bl, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - bl);
  ctx.lineTo(x, y + tl);
  ctx.quadraticCurveTo(x, y, x + tl, y);
  ctx.closePath();
}

function truncateText(ctx, text, maxW) {
  if (ctx.measureText(text).width <= maxW) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(t + '…').width > maxW) t = t.slice(0, -1);
  return t + '…';
}

function drawPixelTrainerCanvas(ctx, x, y, scale, capColor) {
  const sleeve = shadeHex(capColor, -28);
  const rect = (rx, ry, rw, rh, fill) => { ctx.fillStyle = fill; ctx.fillRect(x + rx * scale, y + ry * scale, rw * scale, rh * scale); };
  rect(5, 41, 25, 5, 'rgba(18,43,60,0.28)');
  rect(8, 4, 16, 4, capColor); rect(4, 9, 25, 8, capColor);
  rect(9, 5, 11, 4, '#ffd2a0');
  rect(9, 17, 17, 12, '#edc18e');
  rect(7, 18, 6, 9, '#334b47');
  rect(7, 29, 18, 11, '#d7d9b4');
  rect(5, 30, 6, 9, sleeve); rect(23, 30, 5, 9, sleeve);
  rect(9, 40, 6, 6, '#243e50'); rect(20, 40, 6, 6, '#243e50');
}

async function buildShareCanvas() {
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  const data = computeBoardData();
  const { ranked, rankMeta, winners, short, nameCounts, latestDay, fastest, cheapest, bestLocal, medianWin, passPct } = data;
  const winnersOnly = state.chartView === 'winners';
  const cat = state.category;

  const scale = 2;
  const W = 1080;
  const padX = 36, padTop = 32, padBot = 30;
  const cw = W - padX * 2;
  const innerX = padX + 28, innerW = cw - 56;

  const rowHWin = winnersOnly ? 38 : 27;
  const rowHShort = 26;
  const headerH = 84;
  const kpiH = 60;
  const colHeadH = 36;
  const axisH = 28;
  const sectionGap = 24;
  const footH = 54;

  const winBlockH = colHeadH + Math.max(1, winners.length) * rowHWin + axisH;
  const shortBlockH = winnersOnly ? 0 : (sectionGap + colHeadH + Math.max(1, short.length) * rowHShort + axisH);
  const cardH = 26 + headerH + 16 + kpiH + 18 + winBlockH + shortBlockH + 18 + footH + 12;
  const H = padTop + cardH + padBot;

  const canvas = document.createElement('canvas');
  canvas.width = W * scale;
  canvas.height = H * scale;
  const ctx = canvas.getContext('2d');
  ctx.scale(scale, scale);

  ctx.fillStyle = '#f4eed8';
  ctx.fillRect(0, 0, W, H);

  const cx = padX, cy = padTop, ch = cardH;
  ctx.fillStyle = '#1b1915';
  roundRectPath(ctx, cx + 6, cy + 6, cw, ch, 8); ctx.fill();
  ctx.fillStyle = '#fbf8ec'; ctx.strokeStyle = '#1b1915'; ctx.lineWidth = 3;
  roundRectPath(ctx, cx, cy, cw, ch, 8); ctx.fill(); ctx.stroke();

  let y = cy + 26;

  const logoEl = $('brand-logo');
  if (logoEl && logoEl.complete && logoEl.naturalWidth > 0) {
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(logoEl, innerX, y + 6, 58, 58);
    ctx.imageSmoothingEnabled = true;
  }
  const tx = innerX + 74;
  ctx.fillStyle = '#4e473b';
  ctx.font = '600 12px "IBM Plex Mono", monospace';
  ctx.fillText(`POKÉBENCH · ${categoryShort[cat]} LEADERBOARD · ${(latestDay ? formatDay(latestDay) : 'LIVE').toUpperCase()}`, tx, y + 14);

  ctx.fillStyle = '#1b1915';
  ctx.font = '700 34px "Space Grotesk", system-ui, sans-serif';
  const headline = winnersOnly ? `${winners.length} of ${ranked.length} AIs beat Brock.` : `${winners.length} AIs beat Brock. ${short.length} ran out of turns.`;
  ctx.fillText(headline, tx, y + 50);

  ctx.fillStyle = '#4e473b';
  ctx.font = '400 13.5px "Space Grotesk", system-ui, sans-serif';
  ctx.fillText(`Pokémon Red, new save: beat Brock (1st Gym) in 1,000 turns. ${categoryExplain[cat]} Scored from RAM.`, tx, y + 75);

  const pbW = 148, pbH = 54, pbX = innerX + innerW - pbW, pbY = y + 6;
  ctx.fillStyle = '#fcf3d1'; ctx.strokeStyle = '#1b1915'; ctx.lineWidth = 2;
  roundRectPath(ctx, pbX, pbY, pbW, pbH, 5); ctx.fill(); ctx.stroke();
  ctx.fillStyle = '#1b1915'; ctx.font = '700 22px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center'; ctx.fillText(`${passPct}%`, pbX + pbW / 2, pbY + 25);
  ctx.fillStyle = '#4e473b'; ctx.font = '600 9.5px "IBM Plex Mono", monospace';
  ctx.fillText(`BEAT BROCK (${winners.length}/${ranked.length})`, pbX + pbW / 2, pbY + 38);
  const barX = pbX + 14, barY = pbY + 43, barW = pbW - 28;
  ctx.fillStyle = '#437f52'; ctx.fillRect(barX, barY, barW, 5);
  ctx.fillStyle = '#dfa922'; ctx.fillRect(barX, barY, barW * (passPct / 100), 5);
  ctx.strokeStyle = '#1b1915'; ctx.lineWidth = 1; ctx.strokeRect(barX, barY, barW, 5);
  ctx.textAlign = 'left';

  y += headerH + 16;

  ctx.strokeStyle = '#d8cea9'; ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(innerX, y); ctx.lineTo(innerX + innerW, y);
  ctx.moveTo(innerX, y + kpiH); ctx.lineTo(innerX + innerW, y + kpiH);
  ctx.stroke();

  const kpis = winnersOnly ? [
    { sprite: fastest, label: 'FASTEST BOULDER BADGE', name: fastest ? modelName(fastest) : 'None', stat: fastest ? `${fmtNum(fastest.turns_used)} turns` : '—', color: '#7a5404' },
    { sprite: null, label: 'CHEAPEST WINNING RUN', name: cheapest ? modelName(cheapest) : 'None', stat: cheapest ? `${estPlain(cheapest)}${priceText(cheapest)}` : '—', color: '#7a5404' },
    { sprite: null, label: 'MEDIAN WINNING RUN', name: medianWin ? `${fmtNum(medianWin)} turns` : '—', stat: `${winners.length} badge winners`, color: '#4e473b' }
  ] : [
    { sprite: fastest, label: 'FASTEST BOULDER BADGE', name: fastest ? modelName(fastest) : 'None', stat: fastest ? `${fmtNum(fastest.turns_used)} turns` : '—', color: '#7a5404' },
    { sprite: null, label: 'CHEAPEST WINNING RUN', name: cheapest ? modelName(cheapest) : 'None', stat: cheapest ? `${estPlain(cheapest)}${priceText(cheapest)}` : '—', color: '#7a5404' },
    { sprite: null, label: 'FURTHEST LOCAL MODEL', name: bestLocal ? modelName(bestLocal) : 'None', stat: bestLocal ? `${stopLabel(bestLocal)}${finite(furthestTurn(bestLocal)) ? ' · ' + fmtNum(furthestTurn(bestLocal)) + 't' : ''}` : '—', color: '#215730' }
  ];
  const kw = innerW / 3;
  kpis.forEach((k, i) => {
    const kx = innerX + i * kw;
    if (i > 0) { ctx.beginPath(); ctx.moveTo(kx, y + 8); ctx.lineTo(kx, y + kpiH - 8); ctx.stroke(); }
    let px = kx + (i > 0 ? 16 : 0);
    if (k.sprite) {
      drawPixelTrainerCanvas(ctx, px, y + 10, 0.88, jacketColor(k.sprite));
      px += 34;
    }
    ctx.fillStyle = '#4e473b'; ctx.font = '600 10.5px "IBM Plex Mono", monospace';
    ctx.fillText(k.label, px, y + 21);
    ctx.fillStyle = '#1b1915'; ctx.font = '700 16px "Space Grotesk", system-ui, sans-serif';
    const maxNameW = kw - (px - kx) - 115;
    const nameStr = truncateText(ctx, k.name, Math.max(80, maxNameW));
    ctx.fillText(nameStr, px, y + 45);
    const nw = ctx.measureText(nameStr).width;
    ctx.fillStyle = k.color; ctx.font = '600 13px "IBM Plex Mono", monospace';
    ctx.fillText(k.stat, px + nw + 8, y + 45);
  });

  y += kpiH + 18;

  const drawPanel = ({ topY, title, count, note, rows, kind, rowH, showCost }) => {
    ctx.fillStyle = '#1b1915';
    ctx.font = `700 ${winnersOnly ? 18 : 16}px "Space Grotesk", system-ui, sans-serif`;
    ctx.fillText(title, innerX, topY + 18);
    const tw = ctx.measureText(title).width;
    ctx.fillStyle = kind === 'win' ? '#f6d562' : '#d9ebcc';
    ctx.strokeStyle = '#1b1915'; ctx.lineWidth = 1.5;
    roundRectPath(ctx, innerX + tw + 10, topY + 2, 30, 20, 3); ctx.fill(); ctx.stroke();
    ctx.fillStyle = '#1b1915'; ctx.font = '700 12px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center'; ctx.fillText(String(count), innerX + tw + 25, topY + 16); ctx.textAlign = 'left';

    const dirLabel = kind === 'win' ? 'LOWER IS BETTER' : 'FURTHER IS BETTER';
    ctx.font = '700 10.5px "IBM Plex Mono", monospace';
    const pillTxtW = ctx.measureText(dirLabel).width;
    const dPillW = pillTxtW + 28, dPillH = 20;
    const dPillRight = showCost ? innerX + innerW - 84 : innerX + innerW;
    const dPillX = dPillRight - dPillW;
    ctx.fillStyle = kind === 'win' ? '#fcf3d1' : '#d9ebcc';
    ctx.strokeStyle = '#1b1915'; ctx.lineWidth = 1.4;
    roundRectPath(ctx, dPillX, topY + 2, dPillW, dPillH, 3); ctx.fill(); ctx.stroke();
    const ax = dPillX + 10, ay = topY + 12;
    ctx.strokeStyle = '#1b1915'; ctx.lineWidth = 1.8; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.beginPath();
    if (kind === 'win') {
      ctx.moveTo(ax, ay - 4); ctx.lineTo(ax, ay + 4);
      ctx.moveTo(ax - 3, ay + 1); ctx.lineTo(ax, ay + 4); ctx.lineTo(ax + 3, ay + 1);
    } else {
      ctx.moveTo(ax - 4, ay); ctx.lineTo(ax + 4, ay);
      ctx.moveTo(ax + 1, ay - 3); ctx.lineTo(ax + 4, ay); ctx.lineTo(ax + 1, ay + 3);
    }
    ctx.stroke();
    ctx.fillStyle = '#1b1915';
    ctx.textAlign = 'left';
    ctx.fillText(dirLabel, dPillX + 19, topY + 15.5);

    if (showCost) {
      ctx.fillStyle = '#4e473b'; ctx.font = '600 11px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right'; ctx.fillText('COST', innerX + innerW, topY + 16.5);
      ctx.textAlign = 'left';
    } else if (note) {
      ctx.fillStyle = '#4e473b'; ctx.font = '500 11px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right'; ctx.fillText(note, dPillX - 12, topY + 16);
      ctx.textAlign = 'left';
    }

    ctx.strokeStyle = '#1b1915'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(innerX, topY + 28); ctx.lineTo(innerX + innerW, topY + 28); ctx.stroke();

    const rankW = 36;
    const nameW = winnersOnly ? 230 : 258;
    const costW = showCost ? 84 : 0;
    const valGutter = kind === 'win' ? (winnersOnly ? 92 : 68) : 138;
    const plotX = innerX + rankW + nameW;
    const plotW = innerW - rankW - nameW - valGutter - costW;
    const rowsTop = topY + colHeadH;

    const gridFracs = kind === 'win' ? [0.25, 0.5, 0.75, 1.0] : [0.1, 0.4, 0.7, 0.9];
    ctx.save();
    ctx.strokeStyle = '#d8cea9'; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
    gridFracs.forEach(f => {
      const gx = plotX + f * plotW;
      ctx.beginPath(); ctx.moveTo(gx, rowsTop); ctx.lineTo(gx, rowsTop + rows.length * rowH); ctx.stroke();
    });
    ctx.restore();

    rows.forEach((r, i) => {
      const rm = rankMeta.get(r);
      const ry = rowsTop + i * rowH;
      if (kind === 'win' && i === 0) {
        ctx.fillStyle = 'rgba(246, 213, 98, 0.34)';
        roundRectPath(ctx, innerX - 6, ry + 1, innerW + 12, rowH - 2, 4); ctx.fill();
      }
      ctx.fillStyle = (kind === 'win' && i === 0) ? '#1b1915' : '#635a4b';
      ctx.font = `600 ${winnersOnly ? 14 : 12.5}px "IBM Plex Mono", monospace`;
      ctx.textAlign = 'right';
      ctx.fillText(rm.label, innerX + rankW - 10, ry + rowH * 0.66);
      ctx.textAlign = 'left';

      const mName = modelName(r);
      const isLoc = isLocal(r);
      const viaStr = nameCounts[mName] > 1 ? (VIA_LABELS[r.provider] || r.provider || '') : '';
      const extraW = (isLoc ? 50 : 0) + (viaStr ? 76 : 0) + 12;
      ctx.fillStyle = '#1b1915';
      ctx.font = `${(kind === 'win' && i === 0) ? '700' : '600'} ${winnersOnly ? 16 : 14}px "Space Grotesk", system-ui, sans-serif`;
      const dispName = truncateText(ctx, mName, nameW - extraW);
      ctx.fillText(dispName, innerX + rankW, ry + rowH * 0.66);
      let cursorX = innerX + rankW + ctx.measureText(dispName).width;
      if (viaStr) {
        ctx.fillStyle = '#635a4b'; ctx.font = '500 11px "IBM Plex Mono", monospace';
        ctx.fillText(viaStr, cursorX + 7, ry + rowH * 0.65);
        cursorX += ctx.measureText(viaStr).width + 8;
      }
      if (isLoc) {
        ctx.fillStyle = '#d9ebcc'; ctx.strokeStyle = '#1b1915'; ctx.lineWidth = 1.2;
        roundRectPath(ctx, cursorX + 7, ry + rowH * 0.5 - 7.5, 40, 14.5, 2.5); ctx.fill(); ctx.stroke();
        ctx.fillStyle = '#1b1915'; ctx.font = '700 9px "IBM Plex Mono", monospace';
        ctx.fillText('LOCAL', cursorX + 11.5, ry + rowH * 0.5 + 3.5);
      }

      const isNone = kind === 'short' && r.furthest_index < 0;
      const frac = kind === 'win' ? Math.min(1, r.turns_used / 1000) : (isNone ? 0 : (r.furthest_index + 1) / 10);
      const bh = winnersOnly ? 20 : (kind === 'win' && i === 0 ? 16 : 14);
      const by = ry + (rowH - bh) / 2;

      if (kind === 'win') {
        ctx.fillStyle = '#ede4c6'; ctx.strokeStyle = '#d8cea9'; ctx.lineWidth = 1;
        roundRectPath(ctx, plotX, by + 1, plotW, bh - 2, 2); ctx.fill(); ctx.stroke();
      }

      const bw = isNone ? 0 : Math.max(5, frac * plotW);
      if (bw > 0) {
        ctx.fillStyle = kind === 'win' ? (i === 0 ? '#e9b21c' : '#dfa922') : '#437f52';
        ctx.strokeStyle = '#1b1915'; ctx.lineWidth = 1.6;
        roundRectPath(ctx, plotX, by, bw, bh, [0, 3, 3, 0]); ctx.fill(); ctx.stroke();
      }

      ctx.fillStyle = isNone ? '#4e473b' : '#1b1915';
      ctx.font = `${isNone ? '500' : '700'} ${winnersOnly ? 14 : 12.5}px "IBM Plex Mono", monospace`;
      if (kind === 'win') {
        const valStr = winnersOnly ? `${fmtNum(r.turns_used)} turns` : `${fmtNum(r.turns_used)}t`;
        if (frac >= 0.82) {
          ctx.textAlign = 'right';
          ctx.fillText(valStr, plotX + bw - 8, ry + rowH * 0.67);
          ctx.textAlign = 'left';
        } else {
          ctx.fillText(valStr, plotX + bw + 8, ry + rowH * 0.67);
        }
      } else {
        const stopTxt = stopLabel(r);
        ctx.fillText(stopTxt, plotX + bw + (isNone ? 2 : 8), ry + rowH * 0.67);
        const ft = furthestTurn(r);
        if (finite(ft)) {
          const sw = ctx.measureText(stopTxt).width;
          ctx.fillStyle = '#635a4b'; ctx.font = '500 11px "IBM Plex Mono", monospace';
          ctx.fillText(` ${fmtNum(ft)}t`, plotX + bw + 8 + sw, ry + rowH * 0.67);
        }
      }

      if (showCost) {
        ctx.fillStyle = isLoc ? '#215730' : '#4e473b';
        ctx.font = `600 ${winnersOnly ? 13.5 : 12}px "IBM Plex Mono", monospace`;
        ctx.textAlign = 'right';
        ctx.fillText(`${estPlain(r)}${priceText(r)}`, innerX + innerW, ry + rowH * 0.67);
        ctx.textAlign = 'left';
      }
    });

    const axisY = rowsTop + rows.length * rowH + 5;
    ctx.strokeStyle = '#1b1915'; ctx.lineWidth = 1.8;
    ctx.beginPath(); ctx.moveTo(plotX, axisY); ctx.lineTo(plotX + plotW, axisY); ctx.stroke();

    if (kind === 'short') {
      ctx.strokeStyle = '#766d5b'; ctx.lineWidth = 1;
      for (let s = 1; s <= 10; s++) {
        const px = plotX + (s / 10) * plotW;
        ctx.beginPath(); ctx.moveTo(px, axisY); ctx.lineTo(px, axisY + 4); ctx.stroke();
      }
    }

    const ticks = kind === 'win'
      ? [[0, '0', 'left'], [0.25, '250', 'center'], [0.5, '500', 'center'], [0.75, '750', 'center'], [1, '1,000 max', 'right']]
      : [[0.1, 'House', 'center'], [0.4, 'Viridian', 'center'], [0.7, 'Forest', 'center'], [0.9, 'Gym', 'center']];
    ticks.forEach(([f, lbl, align]) => {
      ctx.fillStyle = f === 1 ? '#1b1915' : '#4e473b';
      ctx.font = `${f === 1 ? '700' : '500'} 11px "IBM Plex Mono", monospace`;
      ctx.textAlign = align;
      ctx.fillText(lbl, plotX + f * plotW, axisY + 17);
    });
    ctx.textAlign = 'left';
    return axisY + axisH;
  };

  let nextY = drawPanel({
    topY: y, title: 'Beat Brock', count: winners.length,
    note: '', rows: winners, kind: 'win',
    rowH: rowHWin, showCost: true
  });

  if (!winnersOnly) {
    drawPanel({
      topY: nextY + sectionGap - 8, title: 'Ran out of turns', count: short.length,
      note: 'ties by first hit', rows: short, kind: 'short',
      rowH: rowHShort, showCost: false
    });
  }

  const fy = cy + ch - footH;
  ctx.strokeStyle = '#d8cea9'; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(innerX, fy); ctx.lineTo(innerX + innerW, fy); ctx.stroke();

  let lx = innerX;
  const drawSwatch = (fill, label) => {
    ctx.fillStyle = fill; ctx.strokeStyle = '#1b1915'; ctx.lineWidth = 1.5;
    roundRectPath(ctx, lx, fy + 13, 12, 10, 2); ctx.fill(); ctx.stroke();
    lx += 18;
    ctx.fillStyle = '#4e473b'; ctx.font = '600 11.5px "IBM Plex Mono", monospace';
    ctx.fillText(label, lx, fy + 22);
    lx += ctx.measureText(label).width + 16;
  };
  drawSwatch('#dfa922', 'Beat Brock (turns + cost)');
  if (!winnersOnly) drawSwatch('#437f52', 'Ran out (furthest stop + hit turn)');
  ctx.fillStyle = '#635a4b'; ctx.font = '500 11px "IBM Plex Mono", monospace';
  const line2 = winnersOnly
    ? `${short.length} more ran out · ≈ API-equiv · — price N/A · Billions of parameters vs. one old man.`
    : `≈ API-equiv subscription · — pricing unavailable · Billions of parameters vs. one old man.`;
  ctx.fillText(line2, innerX, fy + 40);

  const pillW = 142, pillH = 30, pillX = innerX + innerW - pillW, pillY = fy + 12;
  ctx.fillStyle = '#1b1915'; roundRectPath(ctx, pillX + 2.5, pillY + 2.5, pillW, pillH, 4); ctx.fill();
  ctx.fillStyle = '#f6d562'; ctx.strokeStyle = '#1b1915'; ctx.lineWidth = 2;
  roundRectPath(ctx, pillX, pillY, pillW, pillH, 4); ctx.fill(); ctx.stroke();
  ctx.fillStyle = '#1b1915'; ctx.font = '700 14.5px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center'; ctx.fillText('pokebench.tv', pillX + pillW / 2, pillY + 20); ctx.textAlign = 'left';

  return canvas;
}

function showToast(msg) {
  const el = $('share-toast');
  el.textContent = msg;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => { el.textContent = ''; }, 2600);
}

$('btn-download-png').addEventListener('click', async () => {
  try {
    const canvas = await buildShareCanvas();
    const link = document.createElement('a');
    link.download = `pokebench-${state.category}-${state.chartView}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
    showToast('Saved 2x PNG!');
  } catch { showToast('Export failed'); }
});

$('btn-copy-png').addEventListener('click', async () => {
  try {
    const canvas = await buildShareCanvas();
    const blob = await new Promise(res => canvas.toBlob(res, 'image/png'));
    if (navigator.clipboard && window.ClipboardItem) {
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
      showToast('Copied PNG!');
    } else {
      showToast('Use Save PNG');
    }
  } catch { showToast('Use Save PNG'); }
});

/* ---- Event wiring ---- */
document.querySelector('.page').addEventListener('click', e => {
  const catBtn = e.target.closest('[data-category]');
  const viewBtn = e.target.closest('[data-view]');
  const fBtn = e.target.closest('[data-filter]');
  const resetBtn = e.target.closest('[data-reset-filters]');
  const runBtn = e.target.closest('[data-uid]');
  if (catBtn) {
    state.category = catBtn.dataset.category;
    state.filter = 'all'; state.stop = 'all'; state.query = ''; $('search-input').value = '';
    syncUrl();
    renderAll(true);
    $('announcer').textContent = `Switched to ${categoryNames[state.category]}.`;
  } else if (viewBtn) {
    state.chartView = viewBtn.dataset.view;
    syncUrl();
    syncCategoryAndViewState();
    renderShareFrame(cachedBoardData || computeBoardData());
  } else if (fBtn) {
    state.filter = fBtn.dataset.filter;
    renderCardGrid(cachedBoardData || computeBoardData(), true);
  } else if (resetBtn) {
    state.filter = 'all'; state.stop = 'all'; state.query = ''; $('search-input').value = '';
    renderCardGrid(cachedBoardData || computeBoardData(), true);
    const firstPill = $('type-filters').querySelector('[data-filter="all"]');
    if (firstPill) firstPill.focus();
  } else if (runBtn) {
    const run = state.runs.find(r => r.uid === runBtn.dataset.uid);
    if (run) openModal(run, runBtn);
  }
});
$('stop-filter').addEventListener('change', e => {
  state.stop = e.target.value;
  renderCardGrid(cachedBoardData || computeBoardData(), true);
});
let searchAnnounceTimer = null;
$('search-input').addEventListener('input', e => {
  state.query = e.target.value;
  renderCardGrid(cachedBoardData || computeBoardData(), false);
  clearTimeout(searchAnnounceTimer);
  searchAnnounceTimer = setTimeout(() => {
    $('announcer').textContent = `Showing ${$('cards-count').textContent}.`;
  }, 280);
});

const modalEl = $('run-modal');
$('modal-close').addEventListener('click', () => modalEl.close());
modalEl.addEventListener('close', () => { pauseReplay(); if (lastFocused && document.contains(lastFocused)) lastFocused.focus(); });
modalEl.addEventListener('click', e => { if (e.target === modalEl) modalEl.close(); });
$('modal-content').addEventListener('click', e => {
  const ctrl = e.target.closest('[data-replay]');
  if (!ctrl) return;
  const rc = ctrl.closest('.run-card'), rep = getReplay(rc);
  if (ctrl.dataset.replay === 'flip') flipCard(rc);
  else if (ctrl.dataset.replay === 'end') endReplay(rep);
  else if (ctrl.dataset.replay === 'restart') playReplay(rep, true);
  else if (rep.playing) pauseReplay(rep); else playReplay(rep);
});

document.addEventListener('visibilitychange', () => { if (document.hidden) pauseReplay(); });

/* ---- Data loading (runs.json built by site/build_runs.py) ---- */
let requestId = 0;
function renderDataState(html, error = false) {
  $('data-state').hidden = false;
  $('data-state').classList.toggle('error', error);
  $('data-state').innerHTML = html;
}

async function loadRuns() {
  const id = ++requestId;
  try {
    const response = await fetch('runs.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const rows = await response.json();
    if (!Array.isArray(rows)) throw new Error('Expected a JSON array');
    if (id !== requestId) return;
    const valid = rows.filter(r => r && typeof r === 'object' && Number.isInteger(r.furthest_index) && r.furthest_index >= -1 && r.furthest_index <= 9 && finite(r.turns_used));
    state.runs = valid.map((r, i) => ({ ...r, uid: `run-${i}`, milestones: Array.isArray(r.milestones) ? r.milestones.filter(m => m && typeof m === 'object') : [] }));
    pauseReplay();
    if (modalEl.open) modalEl.close();
    buildCategoryTabs();
    renderAll(true);
    if (!rows.length) renderDataState(`<h2>No runs yet. Run the harness.</h2><p>The board is waiting for its first contender.</p>`);
    else if (valid.length !== rows.length) renderDataState(`<p>${rows.length - valid.length} invalid ${rows.length - valid.length === 1 ? 'row was' : 'rows were'} skipped. ${valid.length} valid runs loaded. Check the source summaries.</p>`, true);
    else $('data-state').hidden = true;
    $('announcer').textContent = `${state.runs.length} runs loaded.`;
  } catch {
    if (id !== requestId) return;
    state.runs = [];
    buildCategoryTabs();
    renderAll(true);
    renderDataState(`<h2>No runs yet. Run the harness.</h2><p>runs.json is unavailable or unreadable. Serve this folder over HTTP after running site/build_runs.py.</p>`, true);
    $('announcer').textContent = 'No runs available.';
  }
}

/* ---- LIVE pill polling (/api/live from Cloudflare Worker) ---- */
async function pollLive() {
  try {
    const response = await fetch('/api/live', { cache: 'no-store' });
    if (!response.ok) return;
    const status = await response.json();
    state.live = status.live === true;
    $('live-pill').classList.toggle('live', state.live);
    $('live-text').textContent = state.live ? 'LIVE' : 'OFFLINE';
    $('live-pill').title = state.live ? `Live on YouTube: ${status.title || ''}`.trim() : 'PokéBench live on YouTube';
  } catch { /* unreachable: leave the pill as it was */ }
}

pollLive();
setInterval(pollLive, 60000);
loadRuns();
