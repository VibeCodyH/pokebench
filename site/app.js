(() => {
  'use strict';

  // Original pixel tiles and scenery adapted from approved design B.
      const tile=(id,x,y,w,h,extra='')=>`<use href="#art-${id}" x="${x}" y="${y}" width="${w}" height="${h}" ${extra}/>`;
      const walker=(x,y,w,h)=>`<g class="walking-sprite">${tile('trainer',x,y,w,h)}</g>`;
      const path=(d,color,width)=>`<path d="${d}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linejoin="miter"/>`;
      const trail=(d,tint='#d7c693')=>path(d,'#63745b',83)+path(d,tint,73)+`<path d="${d}" fill="none" stroke="#f6e2b2" stroke-width="53" stroke-dasharray="4 11" opacity=".35"/>`;
      const trees=(list,id='pine')=>list.map(([x,y,s=1])=>tile(id,x,y,100*s,130*s)).join('');
      const grass=(x,y,cols,rows,color='#577955')=>`<g color="${color}">${Array.from({length:cols*rows},(_,i)=>tile('grass',x+(i%cols)*41,y+Math.floor(i/cols)*29,38,23)).join('')}</g>`;
      const fence=(x,y,count)=>`<g fill="#e0d0a0" stroke="#526951" stroke-width="3"><path d="M${x} ${y+12}h${count*25}" stroke="#baae86" stroke-width="9"/>${Array.from({length:count},(_,i)=>`<path d="M${x+i*25} ${y}h8v35h-8z"/>`).join('')}</g>`;
      const cloud=(x,y,s=1)=>`<path transform="translate(${x} ${y}) scale(${s})" d="M0 22h20V11h30V0h39v12h30v11h23v16H0z" fill="#f4f3cf" opacity=".52"/>`;
      const art={
        'brock-far':cloud(120,41,1.4)+cloud(653,95,.75)+`<path d="M0 310V254h55v-36h58v-42h55v-37h49v46h51v48h58v37h49v55h59v-47h65v-51h49v-30h46v-39h63v55h48v40h73v-58h54v-67h51V79h52v39h37v46h56v46h55v-31h57v-45h68v37h69v47h46v92z" fill="#87b0a1"/><path d="M0 348v-31h63v-34h61v-33h54v36h45v-23h48v47h61v-13h67v28h67v-69h56v-30h45v61h50v22h49v-43h55v-36h72v-70h51v-28h45v82h49v48h55v-32h57v24h67v-34h62v66h52v37z" fill="#6c998c"/>`,
        'brock-ground':`<path d="M0 430h130v-28h142v30h141v-19h121v29h151v-39h162v-25h169v-20h184v312H0z" fill="#92ad87"/><path d="M0 586h279v-19h444v-15h248v-22h229v140H0z" fill="#bfc497"/>`+trail('M600 670V586H784V529')+tile('gym',830,303,315,244)+tile('rock',774,522,84,59)+tile('rock',1081,537,113,79)+grass(30,574,5,2,'#6b946f')+trees([[1116,399,.8],[1160,434,1.1]],'roundtree'),
        'pewter-far':`<path d="M0 70h178v20h156V63h150v27h178V61h196V39h190v30h152v43H0z" fill="#c0c495"/>`+trees([[20,-23,.9],[144,-5,.75],[998,-20,.9],[1092,34,1]],'roundtree'),
        'pewter-ground':trail('M600 0V84H445V315H600V500')+`<path d="M46 208h273v172H46z" fill="#a4b58c"/><path d="M57 221h250v147H57z" fill="#c1c5a0"/>`+tile('gym',75,157,258,199)+tile('house',871,65,184,154)+fence(857,237,9)+grass(25,397,7,2)+walker(506,282,33,50)+tile('lamp',369,183,31,89)+tile('rock',925,369,77,54)+tile('rock',999,384,49,34),
        'pewter-near':trees([[-66,229,1.7],[1088,285,1.5],[1165,343,1.6]],'roundtree'),
        'forest-far':trees([[-5,-40,1.3],[88,-55,1.4],[185,-49,1.2],[279,-32,1.1],[735,-50,1.3],[842,-60,1.5],[960,-43,1.4],[1090,-61,1.4],[1023,107,1.1],[1,118,1.3],[108,124,1.1],[220,114,1]]),
        'forest-ground':`<path d="M0 75h224v67h111v93H202v122h140v143H0zM1200 82H896v90H780v65h242v102h178z" fill="#366852" opacity=".6"/>`+trail('M600 0V105H420V256H534V419H600V570','#b9b585')+grass(235,279,4,3,'#759764')+grass(740,123,4,3,'#83a369')+trees([[323,70,.9],[857,279,1],[970,342,1.1],[208,384,.8],[658,380,.85]])+walker(458,231,34,51)+tile('rock',330,340,60,42)+`<g fill="#e7df8f"><path d="M313 196h4v4h-4zM729 332h4v4h-4zM851 213h4v4h-4zM372 376h4v4h-4z"/></g>`,
        'forest-near':trees([[-56,211,1.9],[53,307,1.6],[-17,408,1.5],[1103,227,1.7],[1007,389,1.45],[1150,414,1.7]]),
        'viridian-far':trees([[8,-35,1.1],[112,-49,1.2],[235,-31,.9],[871,-23,.9],[970,-14,1.2],[1103,-24,1.3]],'roundtree')+`<path d="M0 444h168v-16h187v25h362v-31h213v26h270v52H0z" fill="#b29269" opacity=".7"/>`,
        'viridian-ground':trail('M600 0V160H724V359H600V500','#dfb882')+tile('house',116,92,235,196)+tile('house',892,216,222,185)+`<path d="M175 157h51v22h-51z" fill="#f5e7c3"/><path d="M195 160h10v16h-10zM189 164h22v8h-22z" fill="#bd5d4f"/>`+fence(861,425,11)+grass(34,322,3,3,'#7c8959')+tile('lamp',644,212,32,91)+tile('lamp',762,329,32,91),
        'viridian-near':trees([[-69,233,1.6],[1147,73,1.5],[26,397,1.25],[1098,392,1.2]],'roundtree'),
        'route-far':`<path d="M0 87h152v36h169v42h143v27h185v-42h176v-38h131V69h244v82H987v30H825v29H660v26H429v-20H285v-38H128v-29H0z" fill="#92b66b"/>`+trees([[28,-23,1.1],[155,8,1],[983,-19,1.1],[1092,-20,1.3]],'roundtree'),
        'route-ground':trail('M600 0V142H432V328H600V500','#e5cf91')+`<path d="M77 234h246v147H77zM796 337h301v113H796z" fill="#7baf61"/>`+grass(91,243,5,4,'#c6d984')+grass(809,347,7,3,'#bdd478')+fence(757,142,13)+walker(483,298,35,53)+tile('rock',322,204,71,50)+tile('rock',979,253,72,50),
        'route-near':trees([[-45,300,1.8],[1098,233,1.65],[1017,407,1.1]],'roundtree')+grass(140,439,4,2,'#59675e'),
        'pallet-far':cloud(690,38,.7)+trees([[31,-33,1.1],[153,-29,1],[1039,-20,1.3],[1147,61,1.25]],'roundtree'),
        'pallet-ground':trail('M600 0V149H462V302H600V392','#ead59a')+tile('house',207,160,265,221)+tile('house',861,48,199,166)+`<path d="M265 278h24v26h-24zM336 278h25v26h-25z" fill="#f7d48a"/><path d="M269 280h5v23h-5zM340 280h5v23h-5z" fill="#fff0b5"/><path d="M299 326h40l35 54h-93z" fill="#f7d48a" opacity=".13"/>`+fence(182,380,12)+walker(495,306,35,53)+tile('lamp',753,151,35,100)+grass(767,342,5,2,'#589251')+`<path d="M0 464h227v-14h190v16h250v-14h241v15h292v83H0z" fill="#58b8be"/><path d="M105 486h97v3h-97zM693 493h147v3H693zM944 518h123v3H944z" fill="#caefcf" opacity=".25"/>`,
        'pallet-near':`<g style="filter:brightness(1.12)">${trees([[-62,276,1.75],[1120,240,1.7],[44,408,1.4],[1035,401,1.2]],'roundtree')}</g>`
      };


  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
  const number = value => finite(value) ? value.toLocaleString('en-US') : '—';
  const textValue = value => value == null || value === '' ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value);
  const local = run => String(run.provider || '').toLowerCase().includes('ollama');
  const won = run => run.furthest_index === 9;
  const costNumber = run => local(run) ? 0 : finite(run.cost_usd) ? run.cost_usd : Infinity;
  const price = run => local(run) ? 'FREE' : finite(run.cost_usd) ? '$' + run.cost_usd.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: run.cost_usd > 0 && run.cost_usd < .01 ? 6 : 2}) : '—';
  const tokens = run => finite(run.tokens_in) && finite(run.tokens_out) ? run.tokens_in + run.tokens_out : null;
  const time = seconds => {
    if (!finite(seconds)) return '—';
    const s = Math.round(seconds), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
    return h ? `${h}h ${m}m` : m ? `${m}m ${s % 60}s` : `${s}s`;
  };
  const milestoneList = [
    {key: 'left_house', label: 'Left the house', short: 'Left house', station: 'pallet'},
    {key: 'got_starter', label: 'Got a starter', short: 'Got starter', station: 'route-one'},
    {key: 'route_1', label: 'Reached Route 1', short: 'Route 1', station: 'route-one'},
    {key: 'viridian_city', label: 'Reached Viridian City', short: 'Viridian City', station: 'viridian'},
    {key: 'got_parcel', label: "Got Oak's Parcel", short: 'Parcel', station: 'viridian'},
    {key: 'got_pokedex', label: 'Got the Pokédex', short: 'Pokédex', station: 'viridian'},
    {key: 'viridian_forest', label: 'Entered Viridian Forest', short: 'Viridian Forest', station: 'forest'},
    {key: 'pewter_city', label: 'Reached Pewter City', short: 'Pewter City', station: 'pewter'},
    {key: 'pewter_gym', label: "Entered Brock's Gym", short: 'Entered gym', station: 'pewter'},
    {key: 'beat_brock', label: 'Beat Brock (Boulder Badge)', short: 'Beat Brock', station: 'brock'}
  ];
  const stations = [
    {id: 'pewter', art: 'pewter', name: 'Pewter City', title: 'So close. Still no badge.', kicker: '8–9 / 10 · THE GYM IS RIGHT THERE', lede: 'Pewter City. The last stop before the rock guy.', indices: [8,7], next: 'forest', nextName: 'Viridian Forest'},
    {id: 'forest', art: 'forest', name: 'Viridian Forest', title: 'Lost in the leaves.', kicker: '7 / 10 · VIRIDIAN FOREST', lede: 'Plenty of context. Very little sense of direction.', indices: [6], next: 'viridian', nextName: 'Viridian City'},
    {id: 'viridian', art: 'viridian', name: 'Viridian City', title: 'A quick breather.', kicker: '4–6 / 10 · VIRIDIAN CITY', lede: 'Heal up. Fetch the parcel. Earn the Pokédex.', indices: [5,4,3], next: 'route-one', nextName: 'Route 1'},
    {id: 'route-one', art: 'route', name: 'Route 1 / Got starter', title: 'The grass has questions.', kicker: '2–3 / 10 · THE FIRST STEPS', lede: 'From picking a starter in Pallet to heading north on Route 1.', indices: [2,1], next: 'pallet', nextName: 'Pallet Town'},
    {id: 'pallet', art: 'pallet', name: "Pallet Town / Red's House", title: 'Home, sweet spawn.', kicker: '1 / 10 · LEFT THE HOUSE', lede: 'A whole world outside. The doorstep counts as progress.', indices: [0,-1], next: 'brock', nextName: 'The only way is up'}
  ];
  const stationName = id => id === 'brock' ? 'Brock’s Gym' : stations.find(s => s.id === id)?.name || 'Pallet Town';
  const milestoneLabel = run => milestoneList[run.furthest_index]?.label || 'No milestone reached';
  const modelName = run => textValue(run.model);
  const trophy = '<svg class="trophy" viewBox="0 0 32 37" aria-hidden="true"><use href="#art-trophy"/></svg>';
  const state = {runs: [], sample: false, selected: new Set(), activeView: 'journey', journeyY: 0, loading: false};
  let localHero = null, requestId = 0, railObserver;

  // Compact harness timestamps have no timezone; use their calendar fields for ordering.
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
  const ascending = (a, b) => a === b ? 0 : a < b ? -1 : 1;
  // Spec tiebreaker: same furthest milestone -> fewer turns to REACH it. turns_used ties every
  // non-winner at budget, so rank on the furthest milestone's first-hit turn instead.
  const furthestTurn = run => { const m = (run.milestones || []).find(x => x && x.key === run.furthest_key); return m && finite(m.turn) ? m.turn : (finite(run.turns_used) ? run.turns_used : Infinity); };
  const rankSort = (a, b) => b.furthest_index - a.furthest_index || ascending(furthestTurn(a), furthestTurn(b)) || modelName(a).localeCompare(modelName(b)) || a.uid.localeCompare(b.uid);
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
    const ribbon = `<div class="card-ribbon"><span>${won(run) ? trophy + 'BADGE EARNED' : '<b class="red" aria-hidden="true">×</b> STUCK HERE'} · #${displayRank(run)}</span>${state.sample ? '<span class="sample-badge">ILLUSTRATIVE DATA</span>' : ''}</div>`;
    return `<article class="run-card ${won(run) ? 'is-winner' : ''} ${full ? 'full-card' : 'compact-card'}" data-run="${run.uid}" data-furthest="${run.furthest_index}" tabindex="0" aria-expanded="false" aria-label="${escape(modelName(run))}, ${escape(milestoneLabel(run))}" aria-describedby="card-flip-help">
      <div class="card-inner"><div class="card-face card-front" aria-hidden="false">${ribbon}
      ${run.uid === localHero ? '<div class="hero-ribbon">★ LOCAL HERO · FURTHEST LOCAL RUN</div>' : ''}
      <div class="card-body"><h3 class="model-name">${escape(modelName(run))}</h3><p class="provider">${escape(textValue(run.provider))}${run.run_name ? ' / '+escape(run.run_name) : ''}</p>
      ${run.in_game_name ? `<p class="ingame-name">plays as <b class="player-name">${escape(run.in_game_name)}</b>${run.rival_name ? ` &middot; rival <b class="rival-name">${escape(run.rival_name)}</b>` : ''}</p>` : ''}
      <div class="card-tags"><span class="tag ${local(run) ? 'local' : 'api'}">${local(run) ? 'LOCAL' : 'API'}</span><span class="tag">${escape(textValue(run.family))}</span><span class="tag">GEN 1 · RED</span></div>
      <p class="furthest"><b>${run.furthest_index+1}/10</b> ${escape(milestoneLabel(run))}</p>${stats(run)}
      ${full ? facts([['Prompt',run.prompt_version],['Route',run.execution_route],['Run date',formatDay(runDay(run))]]) : ''}
      <p class="flip-hint">↻ Flip for the journey replay<span>10 rungs. Every recorded turn.</span></p>
      <div class="card-actions"><button class="compare-select" data-select="${run.uid}" aria-pressed="${selected}" ${!selected && state.selected.size >= 4 ? 'disabled' : ''} aria-label="${selected ? 'Remove' : 'Select'} ${escape(modelName(run))} for comparison">${selected ? '✓ Selected' : '+ Compare'}</button>${inspect(run)}</div>${videoURL(run) ? '' : '<p class="vod-note">No VOD attached</p>'}</div></div>
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
  function scene(station) {
    return `<div class="scene" aria-hidden="true">${['far','ground','near'].map(layer => `<svg class="${layer}" viewBox="0 0 1200 550" preserveAspectRatio="xMidYMin slice">${art[station.art+'-'+layer] || ''}</svg>`).join('')}</div>`;
  }
  function renderJourney() {
    const winners = state.runs.filter(won).sort(rankSort);
    $('gym-tally').textContent = `${winners.length} / ${state.runs.length} RUNS BEAT BROCK`;
    $('winners-wall').innerHTML = winners.length ? winners.map(r => card(r)).join('') : '<div class="vacant-wall"><strong>Your plaque could go here.</strong><p>No champions recorded. Brock is keeping the wall warm.</p></div>';
    $('stations').innerHTML = stations.map(station => {
      const runs = state.runs.filter(r => station.indices.includes(r.furthest_index));
      const groups = station.indices.map(index => {
        const group = runs.filter(r => r.furthest_index === index).sort(rankSort);
        const label = milestoneList[index]?.label || 'Still at Red’s House';
        return `<div id="checkpoint-${index}" class="${group.length ? 'pin-group' : 'empty-checkpoint'}" data-checkpoint="${index}">${group.length ? `<p class="pin-label">${index+1}/10 · ${escape(label)}</p>${group.map(r => card(r)).join('')}` : ''}</div>`;
      }).join('');
      return `<section id="${station.id}" class="station ${station.art}" data-station="${station.id}" aria-labelledby="${station.id}-title"><div class="station-heading"><p class="station-kicker">${station.kicker}</p><h2 id="${station.id}-title">${station.title}</h2><p class="station-lede">${station.lede}</p><p class="station-count">${runs.length} ${runs.length === 1 ? 'RUN ENDED' : 'RUNS ENDED'} HERE</p></div><div class="map-zone">${scene(station)}<div class="map-pins">${groups}</div>${!runs.length ? '<div class="station-empty"><strong>No runs stopped here.</strong><p>An empty patch of the map. For now.</p></div>' : ''}</div><div class="scene-label"><span>${escape(station.name.toUpperCase())}</span><a href="#${station.next}">${station.next === 'brock' ? '↑' : '↓'} ${station.nextName}</a></div></section>`;
    }).join('');
    frameScenes();
    observeJourney();
  }
  function renderTable() {
    if (activeReplay?.card.closest('#table-cards')) pauseReplay();
    const provider = $('provider-filter').value, family = $('family-filter').value, sort = $('sort').value;
    const filtered = state.runs.filter(run => (provider === 'all' || provider === (local(run) ? 'local' : 'api')) && (family === 'all' || String(run.family || 'Unknown') === family));
    filtered.sort((a,b) => {
      if (sort === 'turns') return ascending(finite(a.turns_used) ? a.turns_used : Infinity, finite(b.turns_used) ? b.turns_used : Infinity) || rankSort(a,b);
      if (sort === 'cost') return ascending(costNumber(a),costNumber(b)) || rankSort(a,b);
      if (sort === 'newest') return ascending(runTimestamp(b),runTimestamp(a)) || rankSort(a,b);
      return rankSort(a,b);
    });
    $('run-count').textContent = `${filtered.length} of ${state.runs.length} runs${state.sample ? ' · sample' : ''}`;
    $('table-cards').innerHTML = filtered.length ? filtered.map(run => card(run,true)).join('') : `<div class="no-matches"><h2>${state.runs.length ? 'No runs match these filters.' : 'No runs yet. Run the harness.'}</h2>${state.runs.length ? '<button class="text-button" id="reset-filters">Reset filters</button>' : '<p>Every attempt starts at home. <a href="runs.sample.json" data-load-sample>Load sample data</a> to explore the site.</p>'}</div>`;
    syncSelection();
  }
  function renderTimeline() {
    const days = new Map();
    [...state.runs].sort((a,b) => ascending(runTimestamp(b),runTimestamp(a)) || rankSort(a,b)).forEach(run => {
      const day = runDay(run);
      if (!days.has(day)) days.set(day,[]);
      days.get(day).push(run);
    });
    $('timeline-list').innerHTML = days.size ? [...days].sort(([a],[b]) => b.localeCompare(a)).map(([day,runs]) => `<section class="timeline-day"><h3>${day ? `<time datetime="${day}">${formatDay(day)}</time>` : 'Date not reported'}${state.sample ? '<small class="sample-badge">ILLUSTRATIVE DATA</small>' : ''}</h3><ul>${runs.map(run => `<li><div><strong>${escape(modelName(run))}</strong><small>${escape(textValue(run.run_id))}</small><small>Prompt ${escape(textValue(run.prompt_version))} · ${local(run) ? 'LOCAL' : 'API'}</small></div><p class="timeline-result">${won(run) ? '★ ' : '× '}${escape(milestoneLabel(run))}<span>${number(run.turns_used)} turns · ${price(run)}</span></p>${inspect(run,true)}</li>`).join('')}</ul></section>`).join('') : '<p>No runs yet. The next adventure will appear here.</p>';
  }
  function syncSelection() {
    document.querySelectorAll('[data-select]').forEach(button => {
      const selected = state.selected.has(button.dataset.select);
      button.setAttribute('aria-pressed',String(selected));
      button.disabled = !selected && state.selected.size >= 4;
      button.textContent = selected ? '✓ Selected' : '+ Compare';
      const run = state.runs.find(r => r.uid === button.dataset.select);
      button.setAttribute('aria-label',`${selected ? 'Remove' : 'Select'} ${modelName(run)} for comparison`);
    });
    const selected = state.runs.filter(run => state.selected.has(run.uid));
    $('compare-tray').hidden = !selected.length;
    document.body.classList.toggle('has-selection',!!selected.length);
    $('compare-count').textContent = `${selected.length} / 4 SELECTED${selected.length === 4 ? ' · LIMIT REACHED' : ''}`;
    $('compare-open').disabled = selected.length < 2;
    $('compare-chips').innerHTML = selected.map(run => `<button class="compare-chip" data-remove="${run.uid}" aria-label="Remove ${escape(modelName(run))} from comparison">${escape(modelName(run))} ×</button>`).join('');
  }
  function compare() {
    const runs = [...state.selected].map(uid => state.runs.find(run => run.uid === uid)).filter(Boolean);
    if (runs.length < 2) return;
    const rows = [
      ['Furthest milestone',r => milestoneLabel(r)], ['Turns',r => `${number(r.turns_used)} / ${number(r.budget_turns)}`],
      ['Tokens (in + out)',r => number(tokens(r))],['Tokens in',r => number(r.tokens_in)],['Tokens out',r => number(r.tokens_out)],
      ['Cost',price],['Time',r => time(r.wall_time_s)],['Prompt version',r => textValue(r.prompt_version)],
      ['Execution route',r => textValue(r.execution_route)],['Think level',r => textValue(r.think_level)],
      ['Context',r => number(r.num_ctx)],['Run date',r => formatDay(runDay(r))]
    ];
    $('compare-sample').hidden = !state.sample;
    $('compare-table').innerHTML = `<table><caption>${state.sample ? 'Illustrative sample runs. ' : ''}FREE = no API spend; hardware and electricity excluded. — = unreported.</caption><thead><tr><th scope="col">Metric</th>${runs.map(r => `<th scope="col">${escape(modelName(r))}<small>${escape(textValue(r.run_id))}<br>${local(r) ? 'LOCAL' : 'API'} · ${escape(textValue(r.family))}</small></th>`).join('')}</tr></thead><tbody>${rows.map(([label,value]) => `<tr><th scope="row">${label}</th>${runs.map(r => `<td>${escape(value(r))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    $('compare-dialog').showModal();
  }
  function setView(view, restore = true) {
    if (state.activeView === view) return;
    pauseReplay();
    if (state.activeView === 'journey') state.journeyY = window.scrollY;
    state.activeView = view;
    const journey = view === 'journey';
    $('journey-view').hidden = !journey;
    $('table-view').hidden = journey;
    $('progress-rail').hidden = !journey;
    $('depth-toggle').hidden = !journey;
    $('journey-button').setAttribute('aria-pressed',String(journey));
    $('table-button').setAttribute('aria-pressed',String(!journey));
    window.scrollTo({top: journey && restore ? state.journeyY : 0, behavior: 'instant'});
    if (journey) observeJourney();
  }
  function activeRail(index) {
    const station = milestoneList[index]?.station || 'pallet';
    $('rail-station').textContent = stationName(station);
    document.querySelectorAll('.rail-link').forEach(link => {
      link.classList.toggle('in-station',link.dataset.station === station);
      if (Number(link.dataset.index) === index) link.setAttribute('aria-current','location'); else link.removeAttribute('aria-current');
    });
  }
  function observeJourney() {
    railObserver?.disconnect();
    const headerHeight = $('sample-banner').hidden ? document.querySelector('.masthead').offsetHeight : document.querySelector('.masthead').offsetHeight + $('sample-banner').offsetHeight;
    const probe = Math.min(window.innerHeight - 2, headerHeight + Math.max(40,(window.innerHeight - headerHeight)*.36));
    railObserver = new IntersectionObserver(entries => {
      if (state.activeView !== 'journey') return;
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        const station = entry.target;
        const definition = stations.find(s => s.id === station.id);
        const index = station.classList.contains('pin-group') ? Number(station.dataset.checkpoint) : station.id === 'brock' ? 9 : definition.indices.find(i => state.runs.some(r => r.furthest_index === i)) ?? definition.indices[0];
        activeRail(index);
      });
    },{rootMargin: `-${Math.floor(probe)}px 0px -${Math.max(0,Math.floor(window.innerHeight-probe-2))}px 0px`, threshold: 0});
    document.querySelectorAll('.station, .pin-group').forEach(station => railObserver.observe(station));
  }
  const narrow = matchMedia('(max-width: 560px)'), wide = matchMedia('(min-width: 1700px)');
  // Ultra-wide viewports get a 2000-unit stage so the 1200-unit composition keeps its scale;
  // the extra 400 units each side are dressed with trees, grass and rocks in the station's palette.
  function wideScene(station, layer) {
    const kind = station === 'forest' ? 'pine' : 'roundtree', base = art[station+'-'+layer] || '';
    if (layer === 'far') return base + trees([[-372,-28,1.15],[-232,-14,1],[-118,-36,1.2],[1262,-30,1.1],[1372,-8,1.25],[1512,-32,1]],kind) + cloud(-300,60,.8) + cloud(1420,45,.7);
    if (layer === 'near') return base + trees([[-395,270,1.8],[-300,400,1.5],[1470,250,1.7],[1560,395,1.45]],kind);
    return base + grass(-330,300,4,3,'#a9c77c') + grass(1300,260,4,3,'#a9c77c') + tile('rock',-200,190,64,45) + tile('rock',1440,410,70,49);
  }
  // Recompose the approved tiles for a narrow viewport so buildings remain in shot.
  // The map and attached cards retain separate layers; cards never move with depth.
  function mobileScene(station, layer) {
    const wooded = station === 'forest';
    if (layer === 'far') return trees([[-20,-35,.65],[318,-25,.65]], wooded ? 'pine' : 'roundtree') + (wooded ? trees([[32,-28,.6],[265,-35,.7]]) : cloud(245,18,.45));
    if (layer === 'near') return trees([[-44,340,.8],[362,415,.75],[-40,710,.8]], wooded ? 'pine' : 'roundtree');
    const buildings = {
      pewter: tile('gym',175,8,165,128) + tile('house',24,18,98,81),
      forest: trees([[8,35,.7],[285,50,.7],[310,156,.6]]) + grass(30,129,2,2),
      viridian: tile('house',160,8,155,129) + fence(230,140,5),
      route: tile('house',235,13,123,103) + grass(15,52,3,2) + fence(280,165,4),
      pallet: tile('house',153,3,166,139) + fence(240,157,5) + '<path d="M0 520h70v23h25v95H0z" fill="#58b8be"/>'
    };
    return trail('M195 0V96H123V298H195V820','#e5cf91') + (buildings[station] || '') + walker(111,120,26,39) + grass(15,690,3,2) + tile('rock',320,680,45,31);
  }
  function frameScenes() {
    document.querySelectorAll('.scene svg').forEach(svg => {
      const station = stations.find(s => s.id === svg.closest('.station').id);
      const layer = svg.classList.contains('far') ? 'far' : svg.classList.contains('near') ? 'near' : 'ground';
      svg.setAttribute('viewBox',narrow.matches ? '0 0 390 820' : wide.matches ? '-400 0 2000 550' : '0 0 1200 550');
      svg.innerHTML = narrow.matches ? mobileScene(station.art,layer) : wide.matches ? wideScene(station.art,layer) : art[station.art+'-'+layer] || '';
    });
  }
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let depthEnabled = true;
  function syncMotion() {
    const enabled = depthEnabled && !reduced.matches;
    document.body.classList.toggle('depth-off',!enabled);
    $('depth-toggle').disabled = reduced.matches;
    $('depth-toggle').textContent = reduced.matches ? 'MOTION REDUCED' : enabled ? 'DEPTH ON' : 'DEPTH OFF';
    $('depth-toggle').setAttribute('aria-pressed',String(enabled));
    if (reduced.matches) document.querySelectorAll('.run-card.is-flipped').forEach(card => endReplay(getReplay(card)));
  }
  function renderDataState(message, error = false) {
    $('data-state').hidden = false;
    $('data-state').classList.toggle('error',error);
    $('data-state').innerHTML = `<div><h2>No runs yet. Run the harness.</h2><p>${escape(message)}</p></div><a href="runs.sample.json" data-load-sample>Load sample data →</a>`;
  }
  async function loadRuns(sample = false) {
    const id = ++requestId;
    state.loading = true;
    document.querySelectorAll('[data-load-sample]').forEach(link => link.setAttribute('aria-disabled','true'));
    $('real-data').disabled = true;
    try {
      const response = await fetch(sample ? 'runs.sample.json' : 'runs.json', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const rows = await response.json();
      if (!Array.isArray(rows)) throw new Error('Expected a JSON array');
      if (id !== requestId) return;
      const valid = rows.filter(run => run && typeof run === 'object' && Number.isInteger(run.furthest_index) && run.furthest_index >= -1 && run.furthest_index <= 9 && finite(run.turns_used));
      state.runs = valid.map((run,index) => ({...run, uid: `run-${index}`, milestones: Array.isArray(run.milestones) ? run.milestones.filter(m => m && typeof m === 'object') : []}));
      state.sample = sample;
      finishLoad();
      if (!rows.length) renderDataState('The championship wall is waiting for its first contender.');
      else if (valid.length !== rows.length) {
        $('data-state').hidden = false;
        $('data-state').classList.add('error');
        $('data-state').innerHTML = `<p>${rows.length-valid.length} invalid ${rows.length-valid.length === 1 ? 'row was' : 'rows were'} skipped. ${valid.length} valid runs loaded. Check the source summaries.</p>${!valid.length ? '<a href="runs.sample.json" data-load-sample>Load sample data →</a>' : ''}`;
      } else $('data-state').hidden = true;
      $('announcer').textContent = `${state.runs.length} ${sample ? 'illustrative sample' : 'real'} runs loaded.`;
    } catch (error) {
      if (id !== requestId) return;
      if (sample) {
        $('data-state').hidden = false;
        $('data-state').classList.add('error');
        $('data-state').innerHTML = '<p>Sample data could not be loaded. Your current results are still shown.</p><a href="runs.sample.json" data-load-sample>Try sample data again</a>';
      } else {
        state.runs = []; state.sample = false;
        finishLoad();
        renderDataState('runs.json is unavailable or unreadable. Serve this folder over HTTP after running site/build_runs.py.',true);
      }
      $('announcer').textContent = sample ? 'Sample data could not be loaded.' : 'No runs available.';
    } finally {
      if (id === requestId) { state.loading = false; $('real-data').disabled = false; document.querySelectorAll('[data-load-sample]').forEach(link => link.removeAttribute('aria-disabled')); }
    }
  }
  function finishLoad() {
    pauseReplay();
    state.selected.clear();
    if ($('compare-dialog').open) $('compare-dialog').close();
    document.body.classList.toggle('sample-mode',state.sample);
    $('sample-banner').hidden = !state.sample;
    localHero = [...state.runs].filter(local).sort(rankSort)[0]?.uid || null;
    $('provider-filter').value = 'all';
    $('family-filter').innerHTML = '<option value="all">All families</option>' + [...new Set(state.runs.map(r => String(r.family || 'Unknown')))].sort().map(family => `<option value="${escape(family)}">${escape(family)}</option>`).join('');
    renderJourney(); renderTable(); renderTimeline(); syncSelection();
  }
  $('rail-list').innerHTML = [...milestoneList].reverse().map((m,i) => `<li><a class="rail-link" href="#${m.station}" data-index="${9-i}" data-station="${m.station}" aria-label="Milestone ${10-i}: ${escape(m.label)}"><span class="rail-number">${10-i}</span><span class="rail-text">${m.short}</span></a></li>`).join('');
  $('method-milestones').innerHTML = milestoneList.map(m => `<li>${escape(m.label)}</li>`).join('');
  $('journey-button').addEventListener('click',() => setView('journey'));
  $('table-button').addEventListener('click',() => setView('table'));
  ['provider-filter','family-filter','sort'].forEach(id => $(id).addEventListener('change',renderTable));
  $('real-data').addEventListener('click',() => loadRuns(false));
  $('compare-open').addEventListener('click',compare);
  $('compare-close').addEventListener('click',() => $('compare-dialog').close());
  $('compare-clear').addEventListener('click',() => { state.selected.clear(); syncSelection(); $('announcer').textContent = 'Comparison cleared.'; });
  $('depth-toggle').addEventListener('click',() => { depthEnabled = !depthEnabled; syncMotion(); });
  reduced.addEventListener('change',syncMotion);
  narrow.addEventListener('change',frameScenes);
  wide.addEventListener('change',frameScenes);
  window.addEventListener('resize',observeJourney);
  // Keep sticky offsets accurate when text wraps or the browser is zoomed.
  new ResizeObserver(() => {
    document.documentElement.style.setProperty('--header',document.querySelector('.masthead').offsetHeight+'px');
    document.body.style.setProperty('--banner',$('sample-banner').hidden ? '0px' : $('sample-banner').offsetHeight+'px');
    observeJourney();
  }).observe(document.querySelector('.masthead'));
  new ResizeObserver(() => {
    document.body.style.setProperty('--banner',$('sample-banner').hidden ? '0px' : $('sample-banner').offsetHeight+'px');
    observeJourney();
  }).observe($('sample-banner'));
  // Hide the journey rail when the shared documentation sections are in view.
  new IntersectionObserver(entries => {
    if (state.activeView !== 'journey') return;
    entries.forEach(entry => { $('progress-rail').hidden = !entry.isIntersecting; });
  },{threshold:0}).observe($('journey-view'));
  document.addEventListener('click',event => {
    const sampleLink = event.target.closest('[data-load-sample]');
    if (sampleLink) { event.preventDefault(); if (!state.loading) loadRuns(true); return; }
    if (event.target.closest('#reset-filters')) { $('provider-filter').value = 'all'; $('family-filter').value = 'all'; renderTable(); return; }
    const selection = event.target.closest('[data-select], [data-remove]');
    if (selection) {
      const uid = selection.dataset.select || selection.dataset.remove;
      if (state.selected.has(uid)) state.selected.delete(uid);
      else if (state.selected.size < 4) state.selected.add(uid);
      syncSelection();
      $('announcer').textContent = `${state.selected.size} of 4 runs selected.${state.selected.size === 4 ? ' Limit reached; remove a run to select another.' : ''}`;
      return;
    }
    const control = event.target.closest('[data-replay]');
    if (control) {
      const card = control.closest('.run-card'), replay = getReplay(card);
      if (control.dataset.replay === 'flip') flipCard(card);
      else if (control.dataset.replay === 'end') endReplay(replay);
      else if (control.dataset.replay === 'restart') playReplay(replay,true);
      else if (replay.playing) pauseReplay(replay); else playReplay(replay);
      return;
    }
    const card = event.target.closest('.run-card');
    if (card && !event.target.closest('button,a,input,select,textarea,progress,meter,output,label,summary,[role="button"],[contenteditable],[data-no-flip]')) { flipCard(card); return; }
    const link = event.target.closest('a[href^="#"]');
    if (!link || link.classList.contains('skip')) return;
    const target = $(link.hash.slice(1));
    if (!target) return;
    if (target.closest('#journey-view')) {
      event.preventDefault();
      setView('journey',false);
      const index = link.dataset.index;
      const checkpoint = index !== undefined ? $('checkpoint-'+index) : null;
      const anchor = checkpoint?.classList.contains('pin-group') ? checkpoint : target;
      anchor.scrollIntoView({behavior: reduced.matches ? 'instant' : 'smooth', block:'start'});
      if (index !== undefined) activeRail(Number(index));
      history.replaceState(null,'',link.hash);
      const heading = target.querySelector('h1,h2');
      if (heading) { heading.tabIndex = -1; heading.focus({preventScroll:true}); }
    }
  });
  document.addEventListener('keydown',event => {
    if (event.target.matches('.run-card') && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      if (!event.repeat) flipCard(event.target);
    }
  });
  document.addEventListener('visibilitychange',() => { if (document.hidden) pauseReplay(); });
  // LIVE pill: the Worker answers /api/live from Twitch (worker.js). It reads OFFLINE until a poll says otherwise.
  const livePill = $('live-pill');
  async function pollLive() {
    try {
      const response = await fetch('/api/live', {cache:'no-store'});
      if (!response.ok) return;
      const status = await response.json();
      const live = status.live === true;
      livePill.classList.toggle('is-live', live);
      $('live-text').textContent = live ? 'LIVE' : 'OFFLINE';
      livePill.title = live ? `Live on Twitch: ${status.title || ''}`.trim() : 'PokeBenchTV on Twitch';
    } catch { /* unreachable: leave the pill as it was */ }
  }
  if (livePill) { pollLive(); setInterval(pollLive, 60000); }
  syncMotion(); activeRail(9);
  loadRuns().then(() => {
    const target = $(location.hash.slice(1));
    if (target) target.scrollIntoView({behavior:'instant',block:'start'});
  });

})();
