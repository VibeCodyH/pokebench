// PokéBench leaderboard. Card + journey replay first (shared with the mocks), then the page.
const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const finite = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const number = value => finite(value) ? value.toLocaleString('en-US') : '—';
const textValue = value => value == null || value === '' ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value);
const local = run => String(run.provider || '').toLowerCase().includes('ollama');
const won = run => run.furthest_index === 9;
const price = run => local(run) ? 'FREE' : finite(run.cost_usd) ? '$' + run.cost_usd.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: run.cost_usd > 0 && run.cost_usd < .01 ? 6 : 2}) : '—';
const tokens = run => finite(run.tokens_in) && finite(run.tokens_out) ? run.tokens_in + run.tokens_out : null;
const time = seconds => {
  if (!finite(seconds)) return '—';
  const s = Math.round(seconds), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
  return h ? `${h}h ${m}m` : m ? `${m}m ${s % 60}s` : `${s}s`;
};
const reduced = matchMedia('(prefers-reduced-motion: reduce)');

// The real Gen-1 ladder, 10 rungs (shared.md ordering).
const milestoneList = [
  {key:'left_house', label:'Left the house', short:'Left house'},
  {key:'got_starter', label:'Got a starter', short:'Got starter'},
  {key:'route_1', label:'Reached Route 1', short:'Route 1'},
  {key:'viridian_city', label:'Reached Viridian City', short:'Viridian City'},
  {key:'got_parcel', label:"Got Oak's Parcel", short:'Parcel'},
  {key:'got_pokedex', label:'Got the Pokédex', short:'Pokédex'},
  {key:'viridian_forest', label:'Entered Viridian Forest', short:'Forest'},
  {key:'pewter_city', label:'Reached Pewter City', short:'Pewter City'},
  {key:'pewter_gym', label:"Entered Brock's Gym", short:'Entered gym'},
  {key:'beat_brock', label:'Beat Brock (Boulder Badge)', short:'Beat Brock'}
];
const modelName = run => textValue(run.model);
const milestoneLabel = run => milestoneList[run.furthest_index]?.label || 'No milestone reached';
const trophy = '<svg class="trophy" viewBox="0 0 32 37" aria-hidden="true"><use href="#art-trophy"/></svg>';
let lastFocused = null;
let localHero = null;
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
  const timestamp = runTimestamp(run);
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString().slice(0,10) : '';
}
const formatDay = day => day ? new Date(day + 'T12:00:00Z').toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'}) : 'Date not reported';
// Spec tiebreaker: same furthest milestone -> fewer turns to REACH it. turns_used ties every
// non-winner at budget, so rank on the furthest milestone's first-hit turn instead.
// Unknown arrival stays unknown: a receipt missing its furthest milestone's turn sorts last
// rather than inheriting turns_used, which would invent a first-hit turn it never measured.
const furthestTurn = run => { const m = (run.milestones || []).find(x => x && x.key === run.furthest_key); return m && finite(m.turn) ? m.turn : Infinity; };
const displayRank = run => 1 + state.runs.filter(other => other.furthest_index > run.furthest_index || other.furthest_index === run.furthest_index && furthestTurn(other) < furthestTurn(run)).length;
function videoURL(run) {
  if (typeof run.youtube_url !== 'string' || !run.youtube_url.trim()) return null;
  try { const url = new URL(run.youtube_url); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; } catch { return null; }
}
function inspect(run, compact = false) {
  const url = videoURL(run);
  if (url) return `<a class="inspect" href="${escape(url)}" target="_blank" rel="noopener noreferrer" aria-label="Inspect run: ${escape(modelName(run))} (opens video in a new tab)">inspect run <span aria-hidden="true">↗</span></a>`;
  return compact ? '<span class="vod-unavailable tag">VOD unavailable</span>' : `<button class="inspect" disabled title="No VOD attached" aria-label="Inspect run: ${escape(modelName(run))}, no VOD attached">inspect run ↗</button>`;
}
function stats(run) {
  return `<dl class="stats"><div><dt>TURNS</dt><dd>${number(run.turns_used)} <small>/ ${number(run.budget_turns)}</small></dd></div><div><dt>TOKENS · IN + OUT</dt><dd>${number(tokens(run))}</dd></div><div><dt>COST</dt><dd class="${local(run) ? 'free' : ''}">${price(run)}</dd></div><div><dt>TIME</dt><dd>${time(run.wall_time_s)}</dd></div></dl>`;
}
function facts(entries) {
  return `<dl class="provenance">${entries.map(([label,value]) => `<dt>${escape(label)}</dt><dd>${escape(textValue(value))}</dd>`).join('')}</dl>`;
}
// Coordinates follow the geography; the Pokédex leg doubles back to Pallet.
const tile=(id,x,y,w,h,extra='')=>`<use href="#art-${id}" x="${x}" y="${y}" width="${w}" height="${h}" ${extra}/>`;
const trees=(list,id='pine')=>list.map(([x,y,s=1])=>tile(id,x,y,100*s,130*s)).join('');
const grass=(x,y,cols,rows,color='#577955')=>`<g color="${color}">${Array.from({length:cols*rows},(_,i)=>tile('grass',x+(i%cols)*41,y+Math.floor(i/cols)*29,38,23)).join('')}</g>`;
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
const lineLength = points => points.slice(1).reduce((sum,p,i) => sum + Math.hypot(p[0]-points[i][0],p[1]-points[i][1]),0);
const linePath = points => points.map(([x,y],i) => `${i ? 'L' : 'M'}${x} ${y}`).join(' ');
function linePart(points, fraction) {
  let remaining = lineLength(points) * Math.max(0,Math.min(1,fraction));
  const part = [points[0]];
  for (let i = 1; i < points.length; i++) {
    const a = points[i-1], b = points[i], length = Math.hypot(b[0]-a[0],b[1]-a[1]);
    if (remaining < length) { part.push([a[0]+(b[0]-a[0])*remaining/length,a[1]+(b[1]-a[1])*remaining/length]); break; }
    part.push(b); remaining -= length;
  }
  return part;
}
function ladder(run) {
  const turns = milestoneList.map(m => {
    const receipts = run.milestones.filter(item => item.key === m.key && finite(item.turn));
    return receipts.length ? Math.min(...receipts.map(item => item.turn)) : null;
  });
  return milestoneList.map((m,i) => {
    const turn = turns[i], previous = i ? turns[i-1] : 0;
    return {...m, turn, reached: finite(turn) || i <= run.furthest_index,
      delta: finite(turn) && finite(previous) && turn >= previous ? turn-previous : null};
  });
}
function runMap(run, rungs) {
  const pins = mapPoints.map(([x,y],i) => {
    const rung = rungs[i], label = `${rung.label} · ${finite(rung.turn) ? 'turn '+number(rung.turn) : rung.reached ? 'turn ? (receipt unknown)' : 'not reached'}`;
    return `<button class="map-pin ${rung.reached ? '' : 'unreached'} ${rung.reached && !finite(rung.turn) ? 'unknown' : ''} ${x > 280 ? 'sign-left' : x < 130 ? 'sign-right' : ''}" style="--x:${x/4}%;--y:${y/3}%" data-pin="${i}" aria-label="${escape(label)}"><span aria-hidden="true">${i+1}</span><span class="pin-sign" aria-hidden="true">${escape(label)}</span></button>`;
  }).join('');
  const roads = linePath(mapLegs.flat());
  return `<div class="replay-map" role="group" aria-label="Journey map for ${escape(modelName(run))}">
    <svg class="run-map" viewBox="0 0 400 300" aria-hidden="true"><rect width="400" height="300" fill="#cedfb0"/>
    <path d="M362 0h38v300h-40v-30h15V181h-13zM0 288h84v12H0z" fill="#81c9b1"/>
    <path d="M277 91h78v102h-89v-52h11z" fill="#80a66e"/>
    ${trees([[280,69,.3],[310,58,.3],[343,61,.32],[268,107,.32],[344,108,.35],[277,135,.28],[342,153,.32],[260,183,.3]])}
    ${tile('roundtree',8,112,37,41)}${tile('roundtree',53,167,31,34)}${tile('rock',160,19,32,23)}${grass(192,232,2,2)}
    <path d="${roads}" fill="none" stroke="#849e6c" stroke-width="14" stroke-linejoin="round"/>
    <path d="${roads}" fill="none" stroke="#f2dfac" stroke-width="9" stroke-linejoin="round"/>
    ${tile('house',10,212,58,48)}${tile('house',89,226,59,49)}${tile('house',159,116,53,44)}${tile('house',205,116,53,44)}${tile('house',232,12,57,48)}${tile('gym',34,5,86,66)}
    <g class="map-place-names"><text x="13" y="205">PALLET TOWN</text><text x="139" y="296">LAB</text><text x="172" y="204">ROUTE 1</text><text x="158" y="109">VIRIDIAN CITY</text><text x="296" y="222">ROUTE 2</text><text x="296" y="236">FOREST ↑</text><text x="215" y="85">PEWTER CITY</text><text x="25" y="91">BROCK'S GYM</text></g>
    <path class="replay-trail" d="M${mapStart.join(' ')}"/>
    <g class="replay-skulls"></g><g class="replay-trainer" transform="translate(${mapStart.join(' ')})">${tile('trainer',-8,-24,16,24)}</g>
    <g class="replay-finish" visibility="hidden"></g></svg>${pins}<div class="blackout-overlay" aria-hidden="true"></div></div>
    <p class="map-caption">1–10: ladder order · teal = recorded · gold = replayed<br>${won(run) ? 'Trophy = beat Brock' : 'Red × = estimated stop toward the next rung'} · skull = faint</p>`;
}
function runDetails(run, rungs) {
  const largest = Math.max(-1,...rungs.map(r => r.delta ?? -1));
  const hardest = largest > 0 ? rungs.findIndex(r => r.delta === largest) : -1;
  return `<div class="run-details"><div class="ladder-heading"><b>THE LADDER</b><span>FIRST HIT / SEGMENT TURNS</span></div><ol class="receipt-list">${rungs.map((r,i) => `<li data-rung="${i}" class="${r.reached ? 'pending' : 'unreached'} ${r.reached && !finite(r.turn) ? 'unknown' : ''} ${i === hardest ? 'hardest' : ''}"><span class="rung-number">${i+1}</span><span>${escape(r.short)}${i === hardest ? '<em>tripped up here</em>' : ''}</span><span class="receipt-turn">${finite(r.turn) ? number(r.turn) : r.reached ? '?' : '—'}</span><span class="receipt-delta">${finite(r.delta) ? '+'+number(r.delta) : r.reached ? '?' : '—'}</span></li>`).join('')}</ol>
    <p class="receipt-note">? = unknown receipt or segment · — = unreached. Segment = turns since the previous rung. Missing or out-of-order route timing is estimated; receipts stay as recorded.</p>
    ${facts([['Run ID',run.run_id],['Run name',run.run_name],['Think',run.think_level],['Context',finite(run.num_ctx) ? number(run.num_ctx) : null],
      ['Parameters',run.model_params],['Quant',run.quant],['Token in',number(run.tokens_in)],['Token out',number(run.tokens_out)],['Timestamp',run.timestamp],
      ['Prompt',run.prompt_version],['Route',run.execution_route],['Run date',formatDay(runDay(run))]])}</div>`;
}
function runReplay(run, rungs) {
  const hits = rungs.filter(r => finite(r.turn) && r.turn <= run.turns_used).length;
  return `<div class="replay-toolbar"><div class="replay-controls" role="group" aria-label="Journey replay controls"><button data-replay="play" aria-label="Play replay">Play</button><button data-replay="restart">Restart</button><button data-replay="end">Skip to end</button><span class="replay-status">Ready · ~${Math.round(6+hits*PULSE_MS/1000)}s</span></div>
    <progress class="replay-progress" max="${run.turns_used || 1}" value="0" aria-label="Replay progress in turns"></progress></div>
    ${runMap(run,rungs)}<div class="replay-body"><p class="running-label">RUNNING TOTALS <span>· tokens, cost &amp; time interpolated</span></p>
    <dl class="stats replay-stats"><div><dt>TURNS</dt><dd><span class="counter-stage"><span data-counter="turns">0</span><span class="sparkles" aria-hidden="true"></span></span> <small>/ ${number(run.turns_used)}</small></dd></div><div><dt>TOKENS · IN + OUT</dt><dd data-counter="tokens">${finite(tokens(run)) ? '0' : '—'}</dd></div><div><dt>COST</dt><dd data-counter="cost">${price({...run,cost_usd:finite(run.cost_usd) ? 0 : null})}</dd></div><div><dt>TIME</dt><dd data-counter="time">${finite(run.wall_time_s) ? '0s' : '—'}</dd></div></dl>
    ${runDetails(run,rungs)}</div>`;
}
function card(run, full = false) {
  const selected = state.selected.has(run.uid), rungs = ladder(run);
  const ribbon = `<div class="card-ribbon"><span>${won(run) ? trophy + 'BADGE EARNED' : '<b class="red" aria-hidden="true">×</b> STUCK HERE'} · #${displayRank(run)}</span></div>`;
  return `<article class="run-card ${won(run) ? 'is-winner' : ''} ${full ? 'full-card' : 'compact-card'}" data-run="${run.uid}" data-furthest="${run.furthest_index}" tabindex="0" aria-expanded="false" aria-label="${escape(modelName(run))}, ${escape(milestoneLabel(run))}" aria-describedby="card-flip-help">
    <div class="card-inner"><div class="card-face card-front" aria-hidden="false">${ribbon}
    ${run.uid === localHero ? '<div class="hero-ribbon">★ LOCAL HERO · FURTHEST LOCAL RUN</div>' : ''}
    <div class="card-body"><h3 class="model-name">${escape(modelName(run))}</h3><p class="provider">${escape(textValue(run.provider))}${run.run_name ? ' / '+escape(run.run_name) : ''}</p>
    ${run.in_game_name ? `<p class="ingame-name">plays as <b class="player-name">${escape(run.in_game_name)}</b>${run.rival_name ? ` &middot; rival <b class="rival-name">${escape(run.rival_name)}</b>` : ''}</p>` : ''}
    <div class="card-tags"><span class="tag ${local(run) ? 'local' : 'api'}">${local(run) ? 'LOCAL' : 'API'}</span><span class="tag">${escape(textValue(run.family))}</span><span class="tag">GEN 1 · RED</span></div>
    <p class="furthest"><b>${run.furthest_index+1}/10</b> ${escape(milestoneLabel(run))}</p>${stats(run)}
    ${full ? facts([['Prompt',run.prompt_version],['Route',run.execution_route],['Run date',formatDay(runDay(run))]]) : ''}
    ${full && run.caveat ? `<p class="run-caveat"><b>CAVEAT</b> ${escape(run.caveat)}</p>` : ''}
    <p class="flip-hint">↻ Flip for the journey replay<span>10 rungs. Every recorded turn.</span></p>
    <div class="card-actions">${inspect(run)}</div>${videoURL(run) ? '' : '<p class="vod-note">No VOD attached</p>'}</div></div>
    <div class="card-face card-back" aria-hidden="true" inert>${ribbon}<div class="replay-heading"><h3>${escape(modelName(run))} · Journey</h3><button class="text-button" data-replay="flip">Front ↶</button></div>${runReplay(run,rungs)}</div></div></article>`;
}

// One turn playhead drives the sprite, trail, receipts, counters and faint events.
// Unknown timing is only an animation estimate and never becomes a receipt.
const replays = new WeakMap();
let activeReplay = null;
// Milestone celebration: the turn clock holds for PULSE_MS while the counter grows gold,
// bursts sparkles at full size, sits, then shrinks back and the count resumes.
const PULSE_MS = 1100, BURST_AT = .25;
function replayTimeline(run, rungs) {
  const arrivals = [0];
  let lastKnown = 0;
  for (let i = 0; i <= run.furthest_index; i++) {
    const turn = rungs[i].turn;
    const ordered = finite(turn) && turn >= lastKnown && turn <= run.turns_used;
    arrivals.push(ordered ? turn : null);
    if (ordered) lastKnown = turn;
  }
  arrivals.push(run.turns_used);
  for (let left = 0; left < arrivals.length-1;) {
    let right = left+1;
    while (arrivals[right] === null) right++;
    for (let i = left+1; i < right; i++) arrivals[i] = arrivals[left]+(arrivals[right]-arrivals[left])*(i-left)/(right-left);
    left = right;
  }
  const segments = arrivals.slice(1).map((end,i) => {
    const tail = i > run.furthest_index;
    const stop = mapPoints[run.furthest_index] || mapStart;
    const points = tail ? !won(run) && end > arrivals[i] ? linePart(mapLegs[i],.55) : [stop,stop] : mapLegs[i];
    const known = tail ? run.furthest_index < 0 || finite(rungs[i-1].turn) : finite(rungs[i].delta);
    return {start:arrivals[i],end,points,weight:known ? end-arrivals[i] : run.turns_used/(arrivals.length-1),duration:0};
  });
  // Water-fill the six-second budget, retaining a 250ms floor for short legs.
  let remaining = 6000, open = segments.filter(s => s.end > s.start);
  while (open.length) {
    const weight = open.reduce((sum,s) => sum+s.weight,0);
    const short = open.filter(s => remaining*s.weight/weight < 250);
    if (!short.length) { open.forEach(s => { s.duration = remaining*s.weight/weight; }); break; }
    short.forEach(s => { s.duration = 250; remaining -= 250; });
    open = open.filter(s => !short.includes(s));
  }
  let elapsed = 0;
  segments.forEach(s => { s.at = elapsed; elapsed += s.duration; });
  return {segments,duration:elapsed};
}
function getReplay(card) {
  if (replays.has(card)) return replays.get(card);
  const run = state.runs.find(r => r.uid === card.dataset.run), rungs = ladder(run);
  const timeline = replayTimeline(run,rungs);
  const faints = (Array.isArray(run.blackouts) ? run.blackouts : []).filter(t => finite(t) && t <= run.turns_used).sort((a,b) => a-b).map(turn => {
    let pin = rungs.findIndex(r => finite(r.turn) && r.turn > turn);
    if (pin < 0) pin = Math.min(9,run.furthest_index+1);
    return {turn,pin,at:null};
  });
  const replay = {card,run,rungs,...timeline,faints,turn:-1,elapsed:0,hold:0,burstTimer:0,lastFrame:null,frame:0,playing:false,
    events:[...new Set([...rungs.map(r => r.turn).filter(t => finite(t) && t <= run.turns_used),...faints.map(f => f.turn),run.turns_used])].sort((a,b) => a-b),
    pins:[...card.querySelectorAll('[data-pin]')],rows:[...card.querySelectorAll('[data-rung]')],
    counters:Object.fromEntries([...card.querySelectorAll('[data-counter]')].map(el => [el.dataset.counter,el])),sparks:card.querySelector('.sparkles'),total:card.querySelector('.replay-stats small'),
    sprite:card.querySelector('.replay-trainer'),trail:card.querySelector('.replay-trail'),finish:card.querySelector('.replay-finish'),
    overlay:card.querySelector('.blackout-overlay'),progress:card.querySelector('.replay-progress'),
    play:card.querySelector('[data-replay="play"]'),status:card.querySelector('.replay-status')};
  card.querySelector('.replay-skulls').innerHTML = faints.map((f,i) => {
    const [x,y] = mapPoints[f.pin];
    return `<g class="faint-marker" data-faint="${i}" visibility="hidden" transform="translate(${x+13+(i%3)*7} ${y-38-Math.floor(i/3)*11})"><title>Fainted at turn ${number(f.turn)} · heading to ${escape(rungs[f.pin].label)}</title><path d="M3 0h10v2h3v10h-3v5H3v-5H0V2h3z" fill="#f8f7eb" stroke="#101c20" stroke-width="2"/><path d="M3 5h4v4H3zM10 5h4v4h-4zM7 10h3v3H7zM5 14h2v3H5zM10 14h2v3h-2z" fill="#101c20"/></g>`;
  }).join('');
  replay.skulls = [...card.querySelectorAll('[data-faint]')];
  replay.finish.innerHTML = won(run) ? '<g transform="translate(-10 -32) scale(.65)"><use href="#art-trophy"/></g>' : '<path class="furthest-x" d="M-6-13l12 12m0-12L-6-1" stroke="#a52f24" stroke-width="4"/>';
  replays.set(card,replay);
  drawReplay(replay,0,true);
  return replay;
}
function drawReplay(replay, turn, instant = false) {
  const {run,rungs,segments,counters} = replay, before = replay.turn;
  replay.turn = turn;
  const ratio = run.turns_used ? turn/run.turns_used : 1;
  let walked = [mapStart];
  for (const segment of segments) {
    if (turn < segment.start) break;
    const fraction = segment.end > segment.start ? (turn-segment.start)/(segment.end-segment.start) : 1;
    walked = walked.concat(linePart(segment.points,fraction).slice(1));
    if (fraction < 1) break;
  }
  const [x,y] = walked[walked.length-1];
  replay.sprite.setAttribute('transform',`translate(${x} ${y})`);
  replay.trail.setAttribute('d',linePath(walked));
  replay.finish.setAttribute('visibility',turn >= run.turns_used ? 'visible' : 'hidden');
  replay.finish.setAttribute('transform',`translate(${x} ${y})`);
  replay.sprite.setAttribute('visibility',turn >= run.turns_used ? 'hidden' : 'visible');
  let celebrate = false;
  rungs.forEach((r,i) => {
    const hit = finite(r.turn) && r.turn <= turn;
    replay.pins[i].classList.toggle('is-hit',hit);
    replay.rows[i].classList.toggle('is-hit',hit);
    if (hit && r.turn > before && !instant && !reduced.matches) celebrate = true;
  });
  counters.turns.textContent = number(Math.floor(turn));
  if (celebrate) pulseTurns(replay);
  counters.tokens.textContent = number(finite(tokens(run)) ? Math.round(tokens(run)*ratio) : null);
  counters.cost.textContent = price({...run,cost_usd:finite(run.cost_usd) ? run.cost_usd*ratio : null});
  counters.time.textContent = time(finite(run.wall_time_s) ? run.wall_time_s*ratio : null);
  replay.progress.value = run.turns_used ? turn : 1;
  let darkness = 0;
  replay.faints.forEach((f,i) => {
    if (f.turn <= turn && f.at === null) f.at = instant ? -Infinity : replay.elapsed;
    const age = f.at === null ? -1 : replay.elapsed-f.at;
    replay.skulls[i].setAttribute('visibility',age >= 400 ? 'visible' : 'hidden');
    if (age >= 0 && age < 400) darkness = Math.max(darkness,Math.min(1,age/100,(400-age)/100));
  });
  replay.overlay.style.opacity = darkness;
}
function pulseTurns(replay) {
  const el = replay.counters.turns;
  replay.hold = PULSE_MS;
  el.getAnimations().forEach(a => a.cancel());
  el.animate([
    {transform:'scale(1)',color:'var(--ink)',textShadow:'0 0 0 transparent'},
    {transform:'scale(1.5)',color:'#c98a00',textShadow:'0 0 14px var(--gold)',offset:BURST_AT,easing:'ease-out'},
    {transform:'scale(1.5)',color:'#c98a00',textShadow:'0 0 8px var(--gold)',offset:.75},
    {transform:'scale(1)',color:'var(--ink)',textShadow:'0 0 0 transparent'},
  ],{duration:PULSE_MS,easing:'ease-in-out'});
  // The "/ total" steps back so the grown count has room.
  replay.total.getAnimations().forEach(a => a.cancel());
  replay.total.animate([{opacity:1},{opacity:.12,offset:BURST_AT},{opacity:.12,offset:.75},{opacity:1}],{duration:PULSE_MS});
  clearTimeout(replay.burstTimer);
  replay.burstTimer = setTimeout(() => burstSparkles(replay),PULSE_MS*BURST_AT);
}
function burstSparkles(replay) {
  if (!replay.sparks || !replay.card.isConnected) return;
  const count = 18;
  for (let i = 0; i < count; i++) {
    const spark = document.createElement('i');
    spark.className = 'spark';
    replay.sparks.appendChild(spark);
    const angle = (i/count)*Math.PI*2+(Math.random()-.5)*.6, dist = 30+Math.random()*40;
    spark.animate([
      {transform:'translate(-50%,-50%) rotate(0deg) scale(1)',opacity:1},
      {opacity:1,offset:.55},
      {transform:`translate(calc(-50% + ${(Math.cos(angle)*dist).toFixed(1)}px),calc(-50% + ${(Math.sin(angle)*dist-8).toFixed(1)}px)) rotate(${Math.round(180+Math.random()*270)}deg) scale(.4)`,opacity:0},
    ],{duration:650+Math.random()*350,easing:'cubic-bezier(.1,.8,.3,1)'}).finished.then(() => spark.remove(),() => spark.remove());
  }
}
function clearCelebration(replay) {
  clearTimeout(replay.burstTimer);
  replay.hold = 0;
  [replay.counters.turns,replay.total].forEach(el => el.getAnimations().forEach(a => a.cancel()));
  if (replay.sparks) replay.sparks.replaceChildren();
}
function replayControls(replay) {
  replay.play.textContent = replay.playing ? 'Pause' : replay.turn >= replay.run.turns_used ? 'Replay' : 'Play';
  replay.play.setAttribute('aria-label',replay.playing ? 'Pause replay' : 'Play replay');
  replay.status.textContent = reduced.matches ? 'End · motion reduced' : replay.playing ? 'Playing' : replay.turn >= replay.run.turns_used ? 'Complete' : 'Paused';
  replay.card.classList.toggle('replay-playing',replay.playing);
}
function pauseReplay(replay = activeReplay) {
  if (!replay) return;
  cancelAnimationFrame(replay.frame);
  replay.playing = false; replay.lastFrame = null;
  if (activeReplay === replay) activeReplay = null;
  replayControls(replay);
}
function endReplay(replay) {
  pauseReplay(replay);
  clearCelebration(replay);
  replay.elapsed = replay.duration+400;
  replay.faints.forEach(f => { f.at = -Infinity; });
  drawReplay(replay,replay.run.turns_used,true);
  replayControls(replay);
}
function tickReplay(replay, now) {
  if (!replay.playing) return;
  if (!replay.card.isConnected || replay.card.closest('[hidden]') || document.hidden) { pauseReplay(replay); return; }
  const dt = replay.lastFrame === null ? 0 : now-replay.lastFrame;
  replay.lastFrame = now;
  // The clock stands still while a milestone celebrates; only the hold timer runs down.
  if (replay.hold > 0) {
    replay.hold = Math.max(0,replay.hold-dt);
    replay.frame = requestAnimationFrame(now => tickReplay(replay,now));
    return;
  }
  replay.elapsed += dt;
  const segment = replay.segments.find(s => s.duration && replay.elapsed < s.at+s.duration);
  const target = segment ? segment.start+(segment.end-segment.start)*Math.max(0,(replay.elapsed-segment.at)/segment.duration) : replay.run.turns_used;
  // Land exactly on each receipt/faint for a frame, including after a slow frame.
  const crossing = replay.events.find(t => t > replay.turn && t <= target);
  drawReplay(replay,crossing ?? target);
  if (replay.turn >= replay.run.turns_used && replay.hold <= 0 && replay.faints.every(f => f.at !== null && replay.elapsed-f.at >= 400)) { pauseReplay(replay); return; }
  replay.frame = requestAnimationFrame(now => tickReplay(replay,now));
}
function playReplay(replay, restart = false) {
  pauseReplay();
  if (reduced.matches) { endReplay(replay); return; }
  if (restart || replay.turn >= replay.run.turns_used) {
    clearCelebration(replay);
    replay.elapsed = 0; replay.turn = -1;
    replay.faints.forEach(f => { f.at = null; });
    drawReplay(replay,0,true);
  }
  // Turn-zero faints still get their fade when playback starts.
  replay.faints.filter(f => f.turn === 0 && f.at === -Infinity).forEach(f => { f.at = 0; });
  activeReplay = replay; replay.playing = true; replay.lastFrame = null;
  replayControls(replay);
  replay.frame = requestAnimationFrame(now => tickReplay(replay,now));
}
function flipCard(card) {
  const back = card.getAttribute('aria-expanded') !== 'true';
  card.classList.toggle('is-flipped',back);
  card.setAttribute('aria-expanded',String(back));
  card.focus({preventScroll:true});
  ['front','back'].forEach(face => {
    const el = card.querySelector('.card-'+face), visible = (face === 'back') === back;
    el.inert = !visible; el.setAttribute('aria-hidden',String(!visible));
  });
  if (back) playReplay(getReplay(card)); else pauseReplay(replays.get(card));
}
// ---- end copied block ----------------------------------------------------------------------

function openModal(run, triggerEl) {
  lastFocused = triggerEl || document.activeElement;
  const dialog = $('run-modal'), content = $('modal-content');
  content.innerHTML = card(run, true);
  dialog.showModal();
}

const modal = () => $('run-modal');
$('modal-close').addEventListener('click', () => modal().close());
modal().addEventListener('close', () => {
  pauseReplay();
  if (lastFocused && document.contains(lastFocused)) lastFocused.focus();
});
// Backdrop click = the dialog element itself is the target (content fills it). Measuring the
// content rect instead broke on flip: the shorter face re-centres the dialog mid-event.
modal().addEventListener('click', e => { if (e.target === modal()) modal().close(); });
// Wired once on the stable #modal-content container (its innerHTML is replaced per open),
// mirroring the live site's delegated click/keydown handler for .run-card + [data-replay].
$('modal-content').addEventListener('click', event => {
  const control = event.target.closest('[data-replay]');
  if (control) {
    const rc = control.closest('.run-card'), replay = getReplay(rc);
    if (control.dataset.replay === 'flip') flipCard(rc);
    else if (control.dataset.replay === 'end') endReplay(replay);
    else if (control.dataset.replay === 'restart') playReplay(replay,true);
    else if (replay.playing) pauseReplay(replay); else playReplay(replay);
    return;
  }
  const rc = event.target.closest('.run-card');
  if (rc && !event.target.closest('button,a,input,select,textarea,progress,meter,output,label,summary,[role="button"],[contenteditable],[data-no-flip]')) flipCard(rc);
});
$('modal-content').addEventListener('keydown', event => {
  if (event.target.matches('.run-card') && (event.key === 'Enter' || event.key === ' ')) {
    event.preventDefault();
    if (!event.repeat) flipCard(event.target);
  }
});

// ---- page: podium, race track, filters, ranked grid ----
function jacketColor(run) {
  if (local(run)) return '#3f8f52';
  const p = String(run.provider || '').toLowerCase();
  if (p.includes('openai')) return '#1f8f86';
  if (p.includes('anthropic')) return '#c1694a';
  if (p.includes('google')) return '#3b82c4';
  if (p.includes('xai')) return '#1c2733';
  return '#c9a227';
}
function shade(hex, amt) {
  const n = parseInt(hex.slice(1), 16), r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  const adj = v => Math.max(0, Math.min(255, Math.round(v + amt)));
  return '#' + [adj(r), adj(g), adj(b)].map(v => v.toString(16).padStart(2, '0')).join('');
}
// Same trainer paths as #art-trainer, emitted inline (not <use>) so the cap/jacket fill can be
// swapped per model. Skin, shorts and shoes keep their original colours.
function trainerFor(run, cx, footY) {
  const scale = 34 / 32, cap = jacketColor(run), sleeve = shade(cap, -30);
  const tx = (cx - 16 * scale).toFixed(2), ty = (footY - 46 * scale).toFixed(2);
  return `<g transform="translate(${tx} ${ty}) scale(${scale.toFixed(4)})">`
    + `<path d="M5 41h25v5H5z" fill="#122b3c55"/>`
    + `<path d="M8 4h16v4h5v9H4V9h4z" fill="${cap}"/>`
    + `<path d="M9 5h11v4H9z" fill="#ffd2a0"/>`
    + `<path d="M9 17h17v12H9z" fill="#edc18e"/>`
    + `<path d="M7 18h6v9H7z" fill="#334b47"/>`
    + `<path d="M7 29h18v11H7z" fill="#d7d9b4"/>`
    + `<path d="M5 30h6v9H5zM23 30h5v9h-5z" fill="${sleeve}"/>`
    + `<path d="M9 40h6v6H9zM20 40h6v6h-6z" fill="#243e50"/>`
    + `</g>`;
}
// Spec tiebreaker: same furthest milestone -> fewer turns to REACH it. Every non-winner runs
// to budget, so turns_used ties them all; the milestone's first-hit turn is the discriminator.
const rankSort = (a, b) => b.furthest_index - a.furthest_index || furthestTurn(a) - furthestTurn(b) || String(a.model).localeCompare(String(b.model));
const stopLabel = run => milestoneList[run.furthest_index]?.short || 'No milestone';

const state = { runs: [], type: 'all', stop: null, live: false, selected: new Set() };
const typeMatch = run => state.type === 'all' || (state.type === 'local') === local(run);
const visible = () => state.runs.filter(run => typeMatch(run) && (state.stop === null || run.furthest_index === state.stop));

function podiumMarkup(run, place) {
  if (!run) return '';
  const foot = place === 1 ? 'Champion' : local(run) ? 'Local' : 'API';
  const footCls = place === 1 ? '' : local(run) ? 'local' : 'api';
  return `<button type="button" class="box pod pod-${place} ${place === 1 ? 'first' : ''}" data-uid="${escape(run.uid)}" aria-label="${escape(run.model)}, ${['1st','2nd','3rd'][place - 1]} place, open run details">
    <div class="body">
      <span class="place">${['1st','2nd','3rd'][place - 1]}</span>
      <span class="name">${escape(run.model)}</span>
      <span class="meta">${number(run.turns_used)} turns · ${price(run)}</span>
      <span class="result">${escape(stopLabel(run))}</span>
    </div>
    <svg class="pod-sprite" viewBox="0 0 34 51" aria-hidden="true">${trainerFor(run, 17, 51)}</svg>
    <div class="foot ${footCls}">${foot}</div>
  </button>`;
}

function cardMarkup(run, rank) {
  const done = won(run);
  const width = Math.round((run.furthest_index + 1) / milestoneList.length * 100);
  return `<button type="button" class="box trainer" data-uid="${escape(run.uid)}" aria-label="${escape(run.model)}, rank ${rank}, ${escape(stopLabel(run))}, open run details">
    <div class="body">
      <div class="top"><span class="rank ${rank <= 3 ? 'top3' : ''}">${rank}</span><span class="name">${escape(run.model)}</span></div>
      <div class="kv">
        <div><div class="label">Turns</div><div class="value">${number(run.turns_used)}</div></div>
        <div><div class="label">Run cost</div><div class="value">${price(run)}</div></div>
      </div>
      <div class="tagrow"><span class="ptag ${local(run) ? 'local' : 'api'}">${local(run) ? 'LOCAL' : 'API'}</span><span class="bar" title="${width}%"><i style="width:${width}%"></i></span></div>
    </div>
    <div class="foot ${done ? 'won' : ''}"><span class="sq"></span>${escape(stopLabel(run))}</div>
  </button>`;
}

function render() {
  const ranked = [...state.runs].sort(rankSort);
  $('podium').innerHTML = [ranked[1], ranked[0], ranked[2]].map((run, i) => podiumMarkup(run, [2, 1, 3][i])).join('');

  const rankOf = new Map(ranked.map((run, i) => [run, i + 1]));
  const shown = visible().sort(rankSort);
  $('grid').innerHTML = shown.length ? shown.map(run => cardMarkup(run, rankOf.get(run))).join('')
    : '<div class="empty">No trainers match this filter.</div>';
  $('count').textContent = `${shown.length} of ${state.runs.length} models`;

  $('stops').innerHTML = milestoneList.map((s, i) =>
    `<button type="button" class="stop ${state.stop === null ? 'filled' : ''}" aria-pressed="${state.stop === i}" data-stop="${i}" aria-label="${escape(s.label)}"><i></i><span>${escape(s.short)}</span></button>`).join('');

  const counts = { all: state.runs.length, local: state.runs.filter(local).length, api: state.runs.filter(r => !local(r)).length };
  const chip = state.stop === null ? '' :
    `<span class="chip">Stop: ${escape(milestoneList[state.stop].short)}<button type="button" data-clear aria-label="Clear stop filter">×</button></span>`;
  $('filters').innerHTML = chip + ['all', 'local', 'api'].map(t =>
    `<button type="button" class="btn" data-type="${t}" aria-pressed="${state.type === t}">${t === 'all' ? 'All' : t === 'local' ? 'Local' : 'API'} (${counts[t]})</button>`).join('');

  $('live-pill').classList.toggle('live', state.live);
  $('live-text').textContent = state.live ? 'LIVE' : 'OFFLINE';
}

document.querySelector('.page').addEventListener('click', e => {
  const stop = e.target.closest('[data-stop]');
  const type = e.target.closest('[data-type]');
  const open = e.target.closest('[data-uid]');
  if (stop) { const i = +stop.dataset.stop; state.stop = state.stop === i ? null : i; }
  else if (type) state.type = type.dataset.type;
  else if (e.target.closest('[data-clear]')) state.stop = null;
  else if (open) { const run = state.runs.find(r => r.uid === open.dataset.uid); if (run) openModal(run, open); return; }
  else return;
  render();
});


// ---- data: runs.json (built by site/build_runs.py) ----
let requestId = 0;
function renderDataState(html, error = false) {
  $('data-state').hidden = false;
  $('data-state').classList.toggle('error', error);
  $('data-state').innerHTML = html;
}
async function loadRuns() {
  const id = ++requestId;
  try {
    const response = await fetch('runs.json', {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const rows = await response.json();
    if (!Array.isArray(rows)) throw new Error('Expected a JSON array');
    if (id !== requestId) return;
    const valid = rows.filter(run => run && typeof run === 'object' && Number.isInteger(run.furthest_index) && run.furthest_index >= -1 && run.furthest_index <= 9 && finite(run.turns_used));
    state.runs = valid.map((run, index) => ({...run, uid: `run-${index}`, milestones: Array.isArray(run.milestones) ? run.milestones.filter(m => m && typeof m === 'object') : []}));
    state.stop = null;
    pauseReplay();
    if ($('run-modal').open) $('run-modal').close();
    render();
    if (!rows.length) renderDataState(`<h2>No runs yet. Run the harness.</h2><p>The podium is waiting for its first contender.</p>`);
    else if (valid.length !== rows.length) renderDataState(`<p>${rows.length - valid.length} invalid ${rows.length - valid.length === 1 ? 'row was' : 'rows were'} skipped. ${valid.length} valid runs loaded. Check the source summaries.</p>`, true);
    else $('data-state').hidden = true;
    $('announcer').textContent = `${state.runs.length} runs loaded.`;
  } catch (error) {
    if (id !== requestId) return;
    state.runs = []; render();
    renderDataState(`<h2>No runs yet. Run the harness.</h2><p>runs.json is unavailable or unreadable. Serve this folder over HTTP after running site/build_runs.py.</p>`, true);
    $('announcer').textContent = 'No runs available.';
  }
}
document.addEventListener('visibilitychange', () => { if (document.hidden) pauseReplay(); });

// LIVE pill: the Worker answers /api/live from Twitch (worker.js). It reads OFFLINE until a poll says otherwise.
async function pollLive() {
  try {
    const response = await fetch('/api/live', {cache: 'no-store'});
    if (!response.ok) return;
    const status = await response.json();
    state.live = status.live === true;
    $('live-pill').classList.toggle('live', state.live);
    $('live-text').textContent = state.live ? 'LIVE' : 'OFFLINE';
    $('live-pill').title = state.live ? `Live on Twitch: ${status.title || ''}`.trim() : 'PokeBenchTV on Twitch';
  } catch { /* unreachable: leave the pill as it was */ }
}
pollLive(); setInterval(pollLive, 60000);
loadRuns();
