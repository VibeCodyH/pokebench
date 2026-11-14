/*
 * Stanford BackRub / Google98 PageRank Link Graph & Power Iteration Inspector
 * Authentic 1998 HTML 4.0 / Win95 table chrome + CRT oscilloscope <canvas>
 * Exposes window.Google98Viz: init(containerEl), inspect(targetDocId, searchResponse), pause(), destroy()
 */
(function (global) {
  'use strict';

  var CANVAS_W = 532;
  var CANVAS_H = 360;
  var PLOT_W = 240;
  var PLOT_H = 140;
  var SCRUB_W = 228;
  var SCRUB_H = 16;

  var MAX_SUBGRAPH_NODES = 24;
  var MAX_INBOUND = 9;
  var MAX_OUTBOUND = 5;
  var MAX_COMPETITORS = 4;
  var STEP_INTERVAL_MS = 145;
  var DEFAULT_DAMPING = 0.85;
  var DEFAULT_TOL = 1e-9;
  var MAX_POWER_ITER = 150;

  var SLICE_STYLES = {
    academia: { fill: '#2299ee', stroke: '#99ddff', label: 'Academia (.edu)' },
    popculture: { fill: '#dd4488', stroke: '#ffaacc', label: 'Pop Culture' },
    commerce: { fill: '#22aa55', stroke: '#88ffaa', label: 'Commerce (.com)' },
    other: { fill: '#8899aa', stroke: '#ddeeff', label: 'Web Page' }
  };

  var TRAJ_COLORS = ['#ffcc00', '#33bbff', '#ff66aa', '#33dd77', '#ff9944'];

  var state = {
    containerEl: null,
    domBuilt: false,
    dom: {},
    dataReady: false,
    loadingPromise: null,
    pagesMap: null,
    graph: null,
    stats: null,
    prModel: null,
    targetId: null,
    searchResponse: null,
    queryTerms: [],
    resultById: {},
    historyStack: [],
    subgraph: null,
    particles: [],
    iterK: 0,
    iterPlaying: false,
    lastStepAt: 0,
    lastFrameAt: 0,
    rafId: null,
    hoveredNodeIdx: -1,
    scrubDragging: false,
    pendingInspect: null,
    winListeners: [],
    containerClickHandler: null
  };

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function truncateStr(str, maxLen) {
    var s = String(str || '').replace(/\s+/g, ' ').trim();
    if (s.length <= maxLen) return s;
    var cut = s.slice(0, maxLen - 3);
    var sp = cut.lastIndexOf(' ');
    if (sp > Math.floor(maxLen * 0.5)) cut = cut.slice(0, sp);
    return cut + '...';
  }

  function shortNodeLabel(page) {
    if (!page) return '';
    var title = String(page.title || page.id || '');
    title = title.replace(/^\[[^\]]+\]\s*/, '');
    var sepIdx = -1;
    var seps = [' - ', ' | ', ' -- '];
    for (var i = 0; i < seps.length; i++) {
      var idx = title.indexOf(seps[i]);
      if (idx > 6 && (sepIdx === -1 || idx < sepIdx)) sepIdx = idx;
    }
    if (sepIdx > 0) title = title.slice(0, sepIdx);
    return truncateStr(title, 18);
  }

  function tokenizeText(text) {
    if (!text) return [];
    if (global.Google98Engine && typeof global.Google98Engine.tokenize === 'function') {
      try {
        var toks = global.Google98Engine.tokenize(text);
        if (Array.isArray(toks)) return toks;
      } catch (e) {}
    }
    var raw = String(text).toLowerCase().match(/[a-z0-9]+/g);
    if (!raw) return [];
    var out = [];
    for (var i = 0; i < raw.length; i++) {
      var w = raw[i];
      if (w.length > 4 && w.slice(-3) === 'ies') w = w.slice(0, -3) + 'y';
      else if (w.length > 4 && w.slice(-2) === 'es') w = w.slice(0, -2);
      else if (w.length > 3 && w.slice(-1) === 's' && w.slice(-2) !== 'ss') w = w.slice(0, -1);
      out.push(w);
    }
    return out;
  }

  function countTermMatches(text, queryTerms) {
    if (!text || !queryTerms || !queryTerms.length) return 0;
    var tokens = tokenizeText(text);
    var lower = String(text).toLowerCase();
    var tokenSet = {};
    for (var i = 0; i < tokens.length; i++) tokenSet[tokens[i]] = true;
    var hits = 0;
    for (var j = 0; j < queryTerms.length; j++) {
      var qt = String(queryTerms[j]).toLowerCase();
      if (!qt) continue;
      if (tokenSet[qt] || (qt.length >= 4 && lower.indexOf(qt) !== -1)) hits++;
    }
    return hits;
  }

  function highlightQueryHtml(text, queryTerms) {
    var raw = String(text || '');
    if (!queryTerms || !queryTerms.length) return escapeHtml(raw);
    var cleanTerms = [];
    for (var i = 0; i < queryTerms.length; i++) {
      var t = String(queryTerms[i] || '').replace(/[^a-zA-Z0-9]/g, '');
      if (t.length >= 2) cleanTerms.push(t);
    }
    if (!cleanTerms.length) return escapeHtml(raw);
    var re = new RegExp('\\b(?:' + cleanTerms.join('|') + ')[a-z0-9]*', 'gi');
    var out = '';
    var lastIdx = 0;
    var match;
    while ((match = re.exec(raw)) !== null) {
      if (match.index > lastIdx) {
        out += escapeHtml(raw.slice(lastIdx, match.index));
      }
      out += '<span style="background-color:#ffff66;font-weight:bold;color:#000000;">' + escapeHtml(match[0]) + '</span>';
      lastIdx = re.lastIndex;
    }
    if (lastIdx < raw.length) {
      out += escapeHtml(raw.slice(lastIdx));
    }
    return out;
  }

  function normalizePagesMap(rawPages) {
    if (!rawPages) return null;
    if (typeof rawPages.get === 'function' && typeof rawPages.forEach === 'function') {
      var obj = {};
      rawPages.forEach(function (val, key) {
        if (val && val.id) obj[val.id] = val;
        else if (key) obj[key] = val;
      });
      return obj;
    }
    if (Array.isArray(rawPages)) {
      var map = {};
      for (var i = 0; i < rawPages.length; i++) {
        if (rawPages[i] && rawPages[i].id) map[rawPages[i].id] = rawPages[i];
      }
      return map;
    }
    if (rawPages.pages && Array.isArray(rawPages.pages)) {
      return normalizePagesMap(rawPages.pages);
    }
    if (typeof rawPages === 'object') {
      var keys = Object.keys(rawPages);
      if (keys.length > 0) return rawPages;
    }
    return null;
  }

  function extractFromEngineOrGlobal() {
    var pagesMap = null;
    var graph = null;
    var stats = null;

    if (global.Google98Engine) {
      if (typeof global.Google98Engine.getPagesMap === 'function') {
        pagesMap = normalizePagesMap(global.Google98Engine.getPagesMap());
      }
      if (typeof global.Google98Engine.getGraph === 'function') {
        graph = global.Google98Engine.getGraph();
      }
      if (typeof global.Google98Engine.getStats === 'function') {
        stats = global.Google98Engine.getStats();
      }
    }

    if ((!pagesMap || !graph) && global.GOOGLE98_DATA) {
      if (!pagesMap && global.GOOGLE98_DATA.pages) {
        pagesMap = normalizePagesMap(global.GOOGLE98_DATA.pages);
      }
      if (!graph && global.GOOGLE98_DATA.graph) {
        graph = global.GOOGLE98_DATA.graph;
      }
      if (!stats && global.GOOGLE98_DATA.stats) {
        stats = global.GOOGLE98_DATA.stats;
      }
    }

    if (pagesMap && graph && Array.isArray(graph.edges)) {
      state.pagesMap = pagesMap;
      state.graph = graph;
      state.stats = stats;
      state.dataReady = true;
      return true;
    }
    return false;
  }

  function fetchJson(url) {
    if (typeof global.fetch === 'function') {
      return global.fetch(url).then(function (resp) {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      });
    }
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open('GET', url, true);
      xhr.onreadystatechange = function () {
        if (xhr.readyState !== 4) return;
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch (err) {
            reject(err);
          }
        } else {
          reject(new Error('XHR ' + xhr.status));
        }
      };
      xhr.send();
    });
  }

  function ensureData() {
    if (state.dataReady && state.prModel) return Promise.resolve();
    if (extractFromEngineOrGlobal()) {
      ensurePowerIterationModel();
      return Promise.resolve();
    }
    if (state.loadingPromise) return state.loadingPromise;

    var engineReady = (global.Google98Engine && typeof global.Google98Engine.ready === 'function')
      ? global.Google98Engine.ready()
      : Promise.resolve();

    state.loadingPromise = engineReady
      .catch(function () { return null; })
      .then(function () {
        if (extractFromEngineOrGlobal()) return null;
        return Promise.all([
          fetchJson('data/pages.json'),
          fetchJson('data/graph.json'),
          fetchJson('data/stats.json').catch(function () { return null; })
        ]).then(function (arr) {
          state.pagesMap = normalizePagesMap(arr[0]);
          state.graph = arr[1];
          state.stats = arr[2];
          state.dataReady = !!(state.pagesMap && state.graph);
        });
      })
      .then(function () {
        state.loadingPromise = null;
        if (state.dataReady) ensurePowerIterationModel();
      });

    return state.loadingPromise;
  }

  function ensurePowerIterationModel() {
    if (state.prModel) return state.prModel;
    var pagesMap = state.pagesMap || {};
    var graph = state.graph || {};
    var rawEdges = graph.edges || [];

    var idSet = {};
    var mapKeys = Object.keys(pagesMap);
    for (var i = 0; i < mapKeys.length; i++) idSet[mapKeys[i]] = true;
    for (var e = 0; e < rawEdges.length; e++) {
      var item = rawEdges[e];
      var sId = Array.isArray(item) ? item[0] : (item.source_id || item.source);
      var tId = Array.isArray(item) ? item[1] : (item.target_id || item.target);
      if (sId) idSet[sId] = true;
      if (tId) idSet[tId] = true;
    }

    var nodeIds = Object.keys(idSet).sort();
    var N = nodeIds.length;
    if (N === 0) return null;

    var idToIdx = {};
    for (var n = 0; n < N; n++) idToIdx[nodeIds[n]] = n;

    var outAdj = new Array(N);
    var inAdj = new Array(N);
    for (var a = 0; a < N; a++) {
      outAdj[a] = [];
      inAdj[a] = [];
    }

    for (var j = 0; j < rawEdges.length; j++) {
      var edge = rawEdges[j];
      var srcId = Array.isArray(edge) ? edge[0] : (edge.source_id || edge.source);
      var dstId = Array.isArray(edge) ? edge[1] : (edge.target_id || edge.target);
      var anchor = Array.isArray(edge) ? (edge[2] || '') : (edge.anchor_text || '');
      var u = idToIdx[srcId];
      var v = idToIdx[dstId];
      if (u === undefined || v === undefined) continue;
      outAdj[u].push({ dstIdx: v, anchor: anchor });
      inAdj[v].push({ srcIdx: u, anchor: anchor });
    }

    var outDeg = new Int32Array(N);
    var dangling = [];
    for (var dIdx = 0; dIdx < N; dIdx++) {
      outDeg[dIdx] = outAdj[dIdx].length;
      if (outDeg[dIdx] === 0) dangling.push(dIdx);
    }

    var damp = (typeof graph.damping === 'number' && graph.damping > 0 && graph.damping < 1)
      ? graph.damping
      : DEFAULT_DAMPING;
    var tol = (typeof graph.tolerance === 'number' && graph.tolerance > 0)
      ? graph.tolerance
      : DEFAULT_TOL;

    var pr0 = new Float64Array(N);
    var initVal = 1.0 / N;
    for (var z = 0; z < N; z++) pr0[z] = initVal;

    var prHistory = [pr0];
    var residuals = [1.0];
    var cur = pr0;

    for (var k = 1; k <= MAX_POWER_ITER; k++) {
      var dangleSum = 0.0;
      for (var di = 0; di < dangling.length; di++) {
        dangleSum += cur[dangling[di]];
      }
      var base = (1.0 - damp) / N + damp * (dangleSum / N);
      var nxt = new Float64Array(N);
      for (var p = 0; p < N; p++) nxt[p] = base;

      for (var src = 0; src < N; src++) {
        var deg = outDeg[src];
        if (deg === 0) continue;
        var share = damp * cur[src] / deg;
        var links = outAdj[src];
        for (var li = 0; li < links.length; li++) {
          nxt[links[li].dstIdx] += share;
        }
      }

      var l1 = 0.0;
      for (var q = 0; q < N; q++) {
        l1 += Math.abs(nxt[q] - cur[q]);
      }

      prHistory.push(nxt);
      residuals.push(l1);
      cur = nxt;
      if (l1 < tol) break;
    }

    var maxFinalPR = 0.001;
    for (var mp = 0; mp < N; mp++) {
      if (cur[mp] > maxFinalPR) maxFinalPR = cur[mp];
    }

    state.prModel = {
      N: N,
      damping: damp,
      tolerance: tol,
      nodeIds: nodeIds,
      idToIdx: idToIdx,
      outAdj: outAdj,
      inAdj: inAdj,
      outDeg: outDeg,
      prHistory: prHistory,
      residuals: residuals,
      maxFinalPR: maxFinalPR,
      K: prHistory.length - 1
    };
    return state.prModel;
  }

  function getRankAtIter(nodeIdx, k) {
    var model = state.prModel;
    var vec = model.prHistory[k];
    var val = vec[nodeIdx];
    var rank = 1;
    for (var i = 0; i < model.N; i++) {
      if (i === nodeIdx) continue;
      if (vec[i] > val || (vec[i] === val && i < nodeIdx)) rank++;
    }
    return rank;
  }

  function nodeRadius(prVal) {
    var N = state.prModel ? state.prModel.N : 500;
    var r = 5.5 + Math.sqrt(Math.max(0, prVal) * N) * 4.4;
    if (r < 6.5) r = 6.5;
    if (r > 26) r = 26;
    return r;
  }

  function resolveTargetId(rawTargetId, searchResponse) {
    var model = state.prModel;
    if (rawTargetId && model.idToIdx[rawTargetId] !== undefined) return rawTargetId;
    if (rawTargetId && global.Google98Engine && typeof global.Google98Engine.getPageByUrl === 'function') {
      var byUrl = global.Google98Engine.getPageByUrl(rawTargetId);
      if (byUrl && byUrl.id && model.idToIdx[byUrl.id] !== undefined) return byUrl.id;
    }
    if (searchResponse && Array.isArray(searchResponse.results) && searchResponse.results.length > 0) {
      var first = searchResponse.results[0];
      if (first && first.doc && first.doc.id && model.idToIdx[first.doc.id] !== undefined) {
        return first.doc.id;
      }
    }
    if (model.idToIdx['doc_0001'] !== undefined) return 'doc_0001';
    return model.nodeIds[0];
  }

  function extractQueryTerms(searchResponse) {
    if (!searchResponse) return [];
    if (Array.isArray(searchResponse.terms) && searchResponse.terms.length > 0) {
      return searchResponse.terms.slice();
    }
    if (searchResponse.query) {
      return tokenizeText(searchResponse.query);
    }
    return [];
  }

  function buildSubgraph(targetId, searchResponse, queryTerms) {
    var model = state.prModel;
    var pagesMap = state.pagesMap;
    var targetIdx = model.idToIdx[targetId];
    var prConv = model.prHistory[model.K];

    var resultRankMap = {};
    var resultList = (searchResponse && Array.isArray(searchResponse.results)) ? searchResponse.results : [];
    for (var r = 0; r < resultList.length; r++) {
      var item = resultList[r];
      if (item && item.doc && item.doc.id) {
        resultRankMap[item.doc.id] = r + 1;
      }
    }

    var selectedMap = {};
    var orderedNodes = [];

    function addNode(idx, role) {
      if (idx === undefined || idx < 0) return false;
      if (selectedMap[idx]) {
        if (role === 'inbound' && selectedMap[idx].role !== 'target') {
          selectedMap[idx].role = 'inbound';
        }
        return false;
      }
      if (orderedNodes.length >= MAX_SUBGRAPH_NODES) return false;
      var pid = model.nodeIds[idx];
      var page = pagesMap[pid] || { id: pid, title: pid, url: '', slice: 'other', category: '' };
      var sliceKey = SLICE_STYLES[page.slice] ? page.slice : 'other';
      var obj = {
        idx: idx,
        id: pid,
        page: page,
        slice: sliceKey,
        role: role,
        searchRank: resultRankMap[pid] || 0,
        inDeg: model.inAdj[idx].length,
        outDeg: model.outDeg[idx],
        label: shortNodeLabel(page),
        x: CANVAS_W * 0.5,
        y: CANVAS_H * 0.5
      };
      selectedMap[idx] = obj;
      orderedNodes.push(obj);
      return true;
    }

    addNode(targetIdx, 'target');

    // Score inbound links v -> target
    var rawIn = model.inAdj[targetIdx] || [];
    var inboundCandidates = [];
    var seenInSrc = {};
    for (var i = 0; i < rawIn.length; i++) {
      var edgeIn = rawIn[i];
      var matchCnt = countTermMatches(edgeIn.anchor, queryTerms);
      var contrib = model.damping * prConv[edgeIn.srcIdx] / Math.max(1, model.outDeg[edgeIn.srcIdx]);
      if (!seenInSrc[edgeIn.srcIdx]) {
        seenInSrc[edgeIn.srcIdx] = {
          srcIdx: edgeIn.srcIdx,
          anchor: edgeIn.anchor,
          matchCnt: matchCnt,
          contrib: contrib
        };
        inboundCandidates.push(seenInSrc[edgeIn.srcIdx]);
      } else if (matchCnt > seenInSrc[edgeIn.srcIdx].matchCnt) {
        seenInSrc[edgeIn.srcIdx].matchCnt = matchCnt;
        seenInSrc[edgeIn.srcIdx].anchor = edgeIn.anchor;
      }
    }

    inboundCandidates.sort(function (a, b) {
      if ((b.matchCnt > 0) !== (a.matchCnt > 0)) return b.matchCnt > 0 ? 1 : -1;
      if (b.matchCnt !== a.matchCnt) return b.matchCnt - a.matchCnt;
      return b.contrib - a.contrib;
    });

    var inboundQuota = inboundCandidates.length > MAX_INBOUND ? MAX_INBOUND : inboundCandidates.length;
    var selectedInIds = [];
    for (var k = 0; k < inboundQuota; k++) {
      if (addNode(inboundCandidates[k].srcIdx, 'inbound')) {
        selectedInIds.push(inboundCandidates[k].srcIdx);
      }
    }

    // Score outbound links target -> w
    var rawOut = model.outAdj[targetIdx] || [];
    var outboundCandidates = [];
    var seenOut = {};
    for (var o = 0; o < rawOut.length; o++) {
      var dst = rawOut[o].dstIdx;
      if (dst === targetIdx || seenOut[dst]) continue;
      seenOut[dst] = true;
      var dstId = model.nodeIds[dst];
      outboundCandidates.push({
        dstIdx: dst,
        isResult: resultRankMap[dstId] ? 1 : 0,
        pr: prConv[dst]
      });
    }
    outboundCandidates.sort(function (a, b) {
      if (b.isResult !== a.isResult) return b.isResult - a.isResult;
      return b.pr - a.pr;
    });
    var outCount = 0;
    for (var oc = 0; oc < outboundCandidates.length && outCount < MAX_OUTBOUND; oc++) {
      if (addNode(outboundCandidates[oc].dstIdx, 'outbound')) outCount++;
    }

    // Add up to 4 competing search results so user can compare #1 vs #2/#3/#4
    var compAdded = 0;
    for (var cr = 0; cr < resultList.length && compAdded < MAX_COMPETITORS; cr++) {
      var cDoc = resultList[cr] && resultList[cr].doc;
      if (!cDoc || !cDoc.id) continue;
      var cIdx = model.idToIdx[cDoc.id];
      if (cIdx === undefined || cIdx === targetIdx) continue;
      if (addNode(cIdx, 'competitor')) compAdded++;
    }

    // Fill up to ~21 nodes with 2-hop upstream feeders and co-citation hubs
    if (orderedNodes.length < 21) {
      var twoHop = [];
      var seenTwo = {};
      for (var si = 0; si < selectedInIds.length; si++) {
        var hubIdx = selectedInIds[si];
        var feeders = model.inAdj[hubIdx] || [];
        for (var f = 0; f < feeders.length; f++) {
          var fIdx = feeders[f].srcIdx;
          if (!selectedMap[fIdx] && !seenTwo[fIdx]) {
            seenTwo[fIdx] = true;
            twoHop.push({ idx: fIdx, score: prConv[fIdx] / Math.max(1, model.outDeg[fIdx]) });
          }
        }
        var coCited = model.outAdj[hubIdx] || [];
        for (var cc = 0; cc < coCited.length; cc++) {
          var coIdx = coCited[cc].dstIdx;
          if (!selectedMap[coIdx] && !seenTwo[coIdx]) {
            seenTwo[coIdx] = true;
            twoHop.push({ idx: coIdx, score: prConv[coIdx] * 0.85 });
          }
        }
      }
      // Also include top global PR hubs if a leaf had tiny neighborhood
      if (twoHop.length < 8) {
        var topGlobal = [];
        for (var gi = 0; gi < model.N; gi++) {
          if (!selectedMap[gi] && !seenTwo[gi]) {
            topGlobal.push({ idx: gi, score: prConv[gi] });
          }
        }
        topGlobal.sort(function (a, b) { return b.score - a.score; });
        for (var tg = 0; tg < Math.min(8, topGlobal.length); tg++) twoHop.push(topGlobal[tg]);
      }

      twoHop.sort(function (a, b) { return b.score - a.score; });
      for (var th = 0; th < twoHop.length && orderedNodes.length < 22; th++) {
        addNode(twoHop[th].idx, 'secondhop');
      }
    }

    // Build all directed edges within selectedMap
    var edgePairs = {};
    var subEdges = [];
    for (var ni = 0; ni < orderedNodes.length; ni++) {
      var uNode = orderedNodes[ni];
      var outs = model.outAdj[uNode.idx] || [];
      for (var oi = 0; oi < outs.length; oi++) {
        var vIdx = outs[oi].dstIdx;
        if (!selectedMap[vIdx] || vIdx === uNode.idx) continue;
        var key = uNode.idx + '>' + vIdx;
        var mCount = countTermMatches(outs[oi].anchor, queryTerms);
        if (!edgePairs[key]) {
          var role = 'context';
          if (vIdx === targetIdx) role = 'inbound';
          else if (uNode.idx === targetIdx) role = 'outbound';
          var eObj = {
            srcIdx: uNode.idx,
            dstIdx: vIdx,
            srcNode: uNode,
            dstNode: selectedMap[vIdx],
            anchor: outs[oi].anchor || '',
            matchCount: mCount,
            matchesQuery: mCount > 0,
            role: role,
            reciprocal: false,
            ctrlX: 0,
            ctrlY: 0
          };
          edgePairs[key] = eObj;
          subEdges.push(eObj);
        } else if (mCount > edgePairs[key].matchCount) {
          edgePairs[key].matchCount = mCount;
          edgePairs[key].matchesQuery = true;
          edgePairs[key].anchor = outs[oi].anchor || edgePairs[key].anchor;
        }
      }
    }

    for (var ei = 0; ei < subEdges.length; ei++) {
      var ed = subEdges[ei];
      if (edgePairs[ed.dstIdx + '>' + ed.srcIdx]) {
        ed.reciprocal = true;
      }
    }

    // Top 5 ego trajectories (target + top 4 converged PR nodes in subgraph)
    var trajSorted = orderedNodes.slice().sort(function (a, b) {
      if (a.idx === targetIdx) return -1;
      if (b.idx === targetIdx) return 1;
      return prConv[b.idx] - prConv[a.idx];
    });
    var trajNodes = trajSorted.slice(0, 5);

    var subgraph = {
      targetIdx: targetIdx,
      targetNode: selectedMap[targetIdx],
      nodes: orderedNodes,
      nodeByIdx: selectedMap,
      edges: subEdges,
      inboundCandidates: inboundCandidates,
      trajNodes: trajNodes
    };

    layoutSubgraph(subgraph);
    return subgraph;
  }

  function layoutSubgraph(subgraph) {
    var cx = Math.round(CANVAS_W * 0.50);
    var cy = Math.round(CANVAS_H * 0.50);
    var target = subgraph.targetNode;
    target.x = cx;
    target.y = cy;

    var inbound = [];
    var outbound = [];
    var outer = [];

    for (var i = 0; i < subgraph.nodes.length; i++) {
      var n = subgraph.nodes[i];
      if (n.idx === subgraph.targetIdx) continue;
      if (n.role === 'inbound') inbound.push(n);
      else if (n.role === 'outbound') outbound.push(n);
      else outer.push(n);
    }

    // Arrange inbound citing pages along a wide left crescent
    for (var a = 0; a < inbound.length; a++) {
      var fracIn = inbound.length === 1 ? 0.5 : a / (inbound.length - 1);
      var angIn = (112 + fracIn * 136) * (Math.PI / 180);
      var radIn = (a % 2 === 0) ? 128 : 164;
      inbound[a].x = cx + Math.cos(angIn) * radIn;
      inbound[a].y = cy + Math.sin(angIn) * radIn * 0.88;
    }

    // Arrange outbound pages on a right arc
    for (var b = 0; b < outbound.length; b++) {
      var fracOut = outbound.length === 1 ? 0.5 : b / (outbound.length - 1);
      var angOut = (-48 + fracOut * 96) * (Math.PI / 180);
      var radOut = (b % 2 === 0) ? 132 : 162;
      outbound[b].x = cx + Math.cos(angOut) * radOut;
      outbound[b].y = cy + Math.sin(angOut) * radOut * 0.88;
    }

    // Arrange competitors and 2-hop hubs in upper/lower outer sectors
    var outerAngles = [-88, 88, -64, 64, -108, 108, -135, 135, -30, 30, -162, 162];
    for (var c = 0; c < outer.length; c++) {
      var deg = outerAngles[c % outerAngles.length] + Math.floor(c / outerAngles.length) * 14;
      var radAngle = deg * (Math.PI / 180);
      var radOuter = 152 + (c % 2) * 22;
      outer[c].x = cx + Math.cos(radAngle) * radOuter * 1.15;
      outer[c].y = cy + Math.sin(radAngle) * radOuter * 0.86;
    }

    // Deterministic gentle repulsion so labels and circles breathe cleanly
    var nodes = subgraph.nodes;
    var padX = 56;
    var padTop = 36;
    var padBot = 30;
    for (var iter = 0; iter < 75; iter++) {
      for (var i1 = 0; i1 < nodes.length; i1++) {
        var n1 = nodes[i1];
        if (n1.idx === subgraph.targetIdx) continue;
        var fx = 0;
        var fy = 0;
        for (var i2 = 0; i2 < nodes.length; i2++) {
          if (i1 === i2) continue;
          var n2 = nodes[i2];
          var dx = n1.x - n2.x;
          var dy = n1.y - n2.y;
          var distSq = dx * dx + dy * dy;
          if (distSq < 1) distSq = 1;
          var dist = Math.sqrt(distSq);
          var minDist = (n2.idx === subgraph.targetIdx) ? 102 : 76;
          if (dist < minDist) {
            var push = (minDist - dist) * 0.28;
            fx += (dx / dist) * push;
            fy += (dy / dist) * push;
          }
        }
        // Soft pull toward preferred radius from target
        var tdx = n1.x - cx;
        var tdy = n1.y - cy;
        var tDist = Math.sqrt(tdx * tdx + tdy * tdy) || 1;
        var pref = (n1.role === 'inbound' || n1.role === 'outbound') ? 142 : 168;
        var spring = (pref - tDist) * 0.08;
        fx += (tdx / tDist) * spring;
        fy += (tdy / tDist) * spring;

        n1.x += fx;
        n1.y += fy;
        if (n1.x < padX) n1.x = padX;
        if (n1.x > CANVAS_W - padX) n1.x = CANVAS_W - padX;
        if (n1.y < padTop) n1.y = padTop;
        if (n1.y > CANVAS_H - padBot) n1.y = CANVAS_H - padBot;
      }
    }

    // Precompute quadratic Bezier control points for crisp curved directed arcs
    for (var ei = 0; ei < subgraph.edges.length; ei++) {
      var ed = subgraph.edges[ei];
      var sx = ed.srcNode.x;
      var sy = ed.srcNode.y;
      var tx = ed.dstNode.x;
      var ty = ed.dstNode.y;
      var mx = (sx + tx) * 0.5;
      var my = (sy + ty) * 0.5;
      var vx = tx - sx;
      var vy = ty - sy;
      var len = Math.sqrt(vx * vx + vy * vy) || 1;
      var nx = -vy / len;
      var ny = vx / len;
      var bend = ed.reciprocal ? 22 : (ed.role === 'context' ? 12 : 16);
      if (!ed.reciprocal && ((ed.srcIdx + ed.dstIdx) % 2 === 1)) bend = -bend;
      ed.ctrlX = mx + nx * bend;
      ed.ctrlY = my + ny * bend;
    }
  }

  function spawnParticles(subgraph) {
    var particles = [];
    if (!subgraph || !state.prModel) {
      state.particles = particles;
      return;
    }
    var model = state.prModel;
    var prConv = model.prHistory[model.K];

    for (var i = 0; i < subgraph.edges.length; i++) {
      var ed = subgraph.edges[i];
      if (ed.role === 'context' && !ed.matchesQuery) continue;
      var mass = model.damping * prConv[ed.srcIdx] / Math.max(1, model.outDeg[ed.srcIdx]);
      var count = ed.role === 'inbound' ? (mass > 0.0012 ? 3 : 2) : 1;
      if (ed.matchesQuery && count < 3) count = 3;
      for (var p = 0; p < count; p++) {
        particles.push({
          edge: ed,
          t: (p / count) + ((i * 0.13) % 0.25),
          speed: (ed.role === 'inbound' ? 0.34 : 0.24) + Math.min(0.22, mass * 90),
          size: ed.matchesQuery ? 2.8 : (ed.role === 'inbound' ? 2.4 : 1.8)
        });
      }
    }
    state.particles = particles;
  }

  function evalBezier(x0, y0, cx, cy, x1, y1, t) {
    var mt = 1 - t;
    return {
      x: mt * mt * x0 + 2 * mt * t * cx + t * t * x1,
      y: mt * mt * y0 + 2 * mt * t * cy + t * t * y1
    };
  }

  function evalBezierTangent(x0, y0, cx, cy, x1, y1, t) {
    var mt = 1 - t;
    return {
      dx: 2 * mt * (cx - x0) + 2 * t * (x1 - cx),
      dy: 2 * mt * (cy - y0) + 2 * t * (y1 - cy)
    };
  }

  function boxesOverlap(a, b) {
    return !(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y);
  }

  function drawCRTGraticule(ctx, w, h, cx, cy) {
    ctx.fillStyle = '#060d1f';
    ctx.fillRect(0, 0, w, h);

    ctx.strokeStyle = '#0d1d3a';
    ctx.lineWidth = 1;
    var step = 38;
    ctx.beginPath();
    for (var x = step; x < w; x += step) {
      ctx.moveTo(x + 0.5, 0);
      ctx.lineTo(x + 0.5, h);
    }
    for (var y = step; y < h; y += step) {
      ctx.moveTo(0, y + 0.5);
      ctx.lineTo(w, y + 0.5);
    }
    ctx.stroke();

    if (cx !== undefined && cy !== undefined) {
      ctx.strokeStyle = '#11254a';
      ctx.beginPath();
      ctx.arc(cx, cy, 90, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(cx, cy, 155, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  function drawArrowHead(ctx, tipX, tipY, angle, size, color) {
    ctx.save();
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(tipX - size * Math.cos(angle - 0.42), tipY - size * Math.sin(angle - 0.42));
    ctx.lineTo(tipX - size * Math.cos(angle + 0.42), tipY - size * Math.sin(angle + 0.42));
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  function renderGraphCanvas() {
    var canvas = state.dom.graphCanvas;
    if (!canvas || !state.subgraph || !state.prModel) return;
    var ctx = canvas.getContext('2d');
    var sg = state.subgraph;
    var prVec = state.prModel.prHistory[state.iterK];
    var hovIdx = state.hoveredNodeIdx;

    drawCRTGraticule(ctx, CANVAS_W, CANVAS_H, sg.targetNode.x, sg.targetNode.y);

    // 1. Draw edges in 3 crisp layers (context -> normal -> highlighted/matching)
    var pass;
    for (pass = 0; pass < 3; pass++) {
      for (var ei = 0; ei < sg.edges.length; ei++) {
        var ed = sg.edges[ei];
        var isHoveredEdge = (hovIdx !== -1) && (ed.srcIdx === hovIdx || ed.dstIdx === hovIdx);
        var isHighlight = ed.matchesQuery || isHoveredEdge;

        if (pass === 0 && (ed.role !== 'context' || isHighlight)) continue;
        if (pass === 1 && (ed.role === 'context' || isHighlight)) continue;
        if (pass === 2 && !isHighlight) continue;

        var strokeColor = '#1c3760';
        var lineWidth = 1.0;
        var alpha = 0.72;
        if (ed.role === 'inbound') {
          strokeColor = '#3399ee';
          lineWidth = 1.4;
          alpha = 0.88;
        } else if (ed.role === 'outbound') {
          strokeColor = '#2d8a75';
          lineWidth = 1.3;
          alpha = 0.82;
        }
        if (ed.matchesQuery) {
          strokeColor = '#ffcc00';
          lineWidth = 2.2;
          alpha = 0.96;
        }
        if (isHoveredEdge) {
          strokeColor = ed.matchesQuery ? '#ffee66' : '#ffffff';
          lineWidth = 2.1;
          alpha = 1.0;
        }

        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = lineWidth;
        ctx.beginPath();
        ctx.moveTo(ed.srcNode.x, ed.srcNode.y);
        ctx.quadraticCurveTo(ed.ctrlX, ed.ctrlY, ed.dstNode.x, ed.dstNode.y);
        ctx.stroke();

        // Place arrowhead right outside destination node's live radius
        var dstR = nodeRadius(prVec[ed.dstIdx]);
        var tArrow = 0.92;
        for (var ts = 0.98; ts >= 0.55; ts -= 0.03) {
          var pt = evalBezier(ed.srcNode.x, ed.srcNode.y, ed.ctrlX, ed.ctrlY, ed.dstNode.x, ed.dstNode.y, ts);
          var distToDst = Math.sqrt(Math.pow(ed.dstNode.x - pt.x, 2) + Math.pow(ed.dstNode.y - pt.y, 2));
          if (distToDst >= dstR + 2.5) {
            tArrow = ts;
            break;
          }
        }
        var tip = evalBezier(ed.srcNode.x, ed.srcNode.y, ed.ctrlX, ed.ctrlY, ed.dstNode.x, ed.dstNode.y, tArrow);
        var tan = evalBezierTangent(ed.srcNode.x, ed.srcNode.y, ed.ctrlX, ed.ctrlY, ed.dstNode.x, ed.dstNode.y, tArrow);
        var ang = Math.atan2(tan.dy, tan.dx);
        var arrowSz = isHighlight ? 8 : (ed.role === 'context' ? 5 : 6.5);
        if (ed.role !== 'context' || isHighlight) {
          drawArrowHead(ctx, tip.x, tip.y, ang, arrowSz, strokeColor);
        }
        ctx.restore();
      }
    }

    // 2. Draw flowing rank-transfer particles
    for (var pi = 0; pi < state.particles.length; pi++) {
      var p = state.particles[pi];
      var ped = p.edge;
      var pos = evalBezier(ped.srcNode.x, ped.srcNode.y, ped.ctrlX, ped.ctrlY, ped.dstNode.x, ped.dstNode.y, p.t % 1);
      var glowColor = ped.matchesQuery ? '#ffcc00' : (ped.role === 'inbound' ? '#55ddff' : '#55ee99');
      ctx.save();
      ctx.globalAlpha = 0.28;
      ctx.fillStyle = glowColor;
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, p.size * 2.3, 0, Math.PI * 2);
      ctx.fill();

      ctx.globalAlpha = 1.0;
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, p.size * 0.9, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // 3. Draw nodes scaled by live PR^(k)(u)
    var reservedBoxes = [];
    for (var ni = 0; ni < sg.nodes.length; ni++) {
      var nd = sg.nodes[ni];
      var r = nodeRadius(prVec[nd.idx]);
      var sStyle = SLICE_STYLES[nd.slice] || SLICE_STYLES.other;
      var isTarget = nd.idx === sg.targetIdx;
      var isHov = nd.idx === hovIdx;

      reservedBoxes.push({ x: nd.x - r - 2, y: nd.y - r - 2, w: (r + 2) * 2, h: (r + 2) * 2 });

      if (isTarget) {
        ctx.save();
        ctx.globalAlpha = 0.35;
        ctx.fillStyle = '#ffcc00';
        ctx.beginPath();
        ctx.arc(nd.x, nd.y, r + 9, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1.0;
        ctx.strokeStyle = '#ffcc00';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(nd.x, nd.y, r + 5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      } else if (nd.searchRank > 0) {
        ctx.save();
        ctx.strokeStyle = '#ff9933';
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        ctx.arc(nd.x, nd.y, r + 3.5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }

      if (isHov) {
        ctx.save();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(nd.x, nd.y, r + 5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }

      ctx.save();
      ctx.fillStyle = sStyle.fill;
      ctx.strokeStyle = isTarget ? '#ffffff' : sStyle.stroke;
      ctx.lineWidth = isTarget ? 2.2 : 1.4;
      ctx.beginPath();
      ctx.arc(nd.x, nd.y, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      // Inner phosphor specular core dot
      ctx.globalAlpha = 0.45;
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(nd.x - r * 0.28, nd.y - r * 0.28, Math.max(1.5, r * 0.22), 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      if (nd.searchRank > 0 && !isTarget) {
        ctx.save();
        ctx.font = 'bold 9px Courier New, Courier, monospace';
        var tag = '#' + nd.searchRank;
        var tw = ctx.measureText(tag).width + 6;
        ctx.fillStyle = '#ff8800';
        ctx.fillRect(nd.x + r - 2, nd.y - r - 6, tw, 12);
        ctx.fillStyle = '#000000';
        ctx.fillText(tag, nd.x + r + 1, nd.y - r + 3);
        ctx.restore();
      }
    }

    // 4. Place crisp non-overlapping node labels (target -> hovered -> competitors -> inbound/outbound)
    var labelOrder = sg.nodes.slice().sort(function (a, b) {
      if (a.idx === sg.targetIdx) return -1;
      if (b.idx === sg.targetIdx) return 1;
      if (a.idx === hovIdx) return -1;
      if (b.idx === hovIdx) return 1;
      if ((b.searchRank > 0) !== (a.searchRank > 0)) return b.searchRank > 0 ? 1 : -1;
      return prVec[b.idx] - prVec[a.idx];
    });

    ctx.font = '10px Arial, Helvetica, sans-serif';
    for (var li = 0; li < labelOrder.length; li++) {
      var lNode = labelOrder[li];
      var nr = nodeRadius(prVec[lNode.idx]);
      var isT = lNode.idx === sg.targetIdx;
      var isH = lNode.idx === hovIdx;
      var txt = lNode.label;
      ctx.font = isT ? 'bold 10px Arial, Helvetica, sans-serif' : '10px Arial, Helvetica, sans-serif';
      var textW = ctx.measureText(txt).width;
      var boxW = textW + 8;
      var boxH = 14;
      var lx = Math.round(lNode.x - boxW * 0.5);
      if (lx < 4) lx = 4;
      if (lx + boxW > CANVAS_W - 4) lx = CANVAS_W - 4 - boxW;
      var ly = Math.round(lNode.y + nr + 5);
      if (ly + boxH > CANVAS_H - 18) ly = Math.round(lNode.y - nr - boxH - 4);
      var lBox = { x: lx, y: ly, w: boxW, h: boxH };

      var collides = false;
      if (!isT && !isH) {
        for (var bi = 0; bi < reservedBoxes.length; bi++) {
          if (boxesOverlap(lBox, reservedBoxes[bi])) {
            collides = true;
            break;
          }
        }
      }
      if (collides) continue;

      reservedBoxes.push(lBox);
      ctx.save();
      ctx.fillStyle = isT ? '#000066' : '#071228';
      ctx.strokeStyle = isT ? '#ffcc00' : (isH ? '#ffffff' : '#244775');
      ctx.lineWidth = 1;
      ctx.fillRect(lBox.x, lBox.y, lBox.w, lBox.h);
      ctx.strokeRect(lBox.x + 0.5, lBox.y + 0.5, lBox.w - 1, lBox.h - 1);
      ctx.fillStyle = isT ? '#ffffaa' : (isH ? '#ffffff' : '#cde4ff');
      ctx.fillText(txt, lBox.x + 4, lBox.y + 10);
      ctx.restore();
    }

    // 5. Place up to 4 anchor-text callouts along key inbound edges
    var calloutEdges = [];
    for (var ce = 0; ce < sg.edges.length; ce++) {
      var cand = sg.edges[ce];
      if (cand.role !== 'inbound' || !cand.anchor) continue;
      calloutEdges.push(cand);
    }
    calloutEdges.sort(function (a, b) {
      if (b.matchesQuery !== a.matchesQuery) return b.matchesQuery ? 1 : -1;
      if (b.matchCount !== a.matchCount) return b.matchCount - a.matchCount;
      return prVec[b.srcIdx] - prVec[a.srcIdx];
    });

    var placedCallouts = 0;
    var tCandidates = [0.48, 0.58, 0.38, 0.66];
    ctx.font = '9px Courier New, Courier, monospace';
    for (var ci = 0; ci < calloutEdges.length && placedCallouts < 4; ci++) {
      var ced = calloutEdges[ci];
      var snippet = '"' + truncateStr(ced.anchor, 22) + '"';
      var cw = ctx.measureText(snippet).width + 8;
      var ch = 13;
      for (var ti = 0; ti < tCandidates.length; ti++) {
        var cpt = evalBezier(ced.srcNode.x, ced.srcNode.y, ced.ctrlX, ced.ctrlY, ced.dstNode.x, ced.dstNode.y, tCandidates[ti]);
        var cxBox = Math.round(cpt.x - cw * 0.5);
        var cyBox = Math.round(cpt.y - ch * 0.5);
        if (cxBox < 6) cxBox = 6;
        if (cxBox + cw > CANVAS_W - 6) cxBox = CANVAS_W - 6 - cw;
        if (cyBox < 20) cyBox = 20;
        if (cyBox + ch > CANVAS_H - 22) cyBox = CANVAS_H - 22 - ch;
        var cBox = { x: cxBox, y: cyBox, w: cw, h: ch };

        var hit = false;
        for (var rbi = 0; rbi < reservedBoxes.length; rbi++) {
          if (boxesOverlap(cBox, reservedBoxes[rbi])) {
            hit = true;
            break;
          }
        }
        if (!hit) {
          reservedBoxes.push(cBox);
          ctx.save();
          ctx.fillStyle = '#08142b';
          ctx.strokeStyle = ced.matchesQuery ? '#ffcc00' : '#4a88cc';
          ctx.lineWidth = 1;
          ctx.fillRect(cBox.x, cBox.y, cBox.w, cBox.h);
          ctx.strokeRect(cBox.x + 0.5, cBox.y + 0.5, cBox.w - 1, cBox.h - 1);
          ctx.fillStyle = ced.matchesQuery ? '#ffdd55' : '#88ccff';
          ctx.fillText(snippet, cBox.x + 4, cBox.y + 9.5);
          ctx.restore();
          placedCallouts++;
          break;
        }
      }
    }

    // 6. Top CRT readout & bottom legend strip
    ctx.save();
    ctx.fillStyle = '#071228';
    ctx.fillRect(0, 0, CANVAS_W, 17);
    ctx.fillStyle = '#44dd88';
    ctx.font = 'bold 10px Courier New, Courier, monospace';
    ctx.fillText('BACKRUB CRT // N=' + state.prModel.N + ' d=' + state.prModel.damping.toFixed(2) + ' k=' + state.iterK + '/' + state.prModel.K, 6, 12);

    ctx.fillStyle = '#aaccff';
    ctx.font = '10px Courier New, Courier, monospace';
    ctx.fillText('SUBGRAPH: ' + sg.nodes.length + ' NODES, ' + sg.edges.length + ' LINKS', 318, 12);

    ctx.fillStyle = '#071228';
    ctx.fillRect(0, CANVAS_H - 17, CANVAS_W, 17);
    var legItems = [
      { color: '#2299ee', text: '.edu' },
      { color: '#dd4488', text: 'PopCulture' },
      { color: '#22aa55', text: '.com' },
      { color: '#ffcc00', text: 'Anchor Match' },
      { color: '#ff9933', text: 'Query Result' }
    ];
    var lxPos = 8;
    ctx.font = '10px Arial, Helvetica, sans-serif';
    for (var lg = 0; lg < legItems.length; lg++) {
      ctx.fillStyle = legItems[lg].color;
      ctx.fillRect(lxPos, CANVAS_H - 12, 8, 8);
      ctx.fillStyle = '#b8d4f0';
      ctx.fillText(legItems[lg].text, lxPos + 12, CANVAS_H - 5);
      lxPos += ctx.measureText(legItems[lg].text).width + 26;
    }
    ctx.restore();
  }

  function renderPlotCanvas() {
    var canvas = state.dom.plotCanvas;
    if (!canvas || !state.prModel || !state.subgraph) return;
    var ctx = canvas.getContext('2d');
    var model = state.prModel;
    var realK = model.K;
    var K = Math.max(1, realK);
    var padL = 28;
    var padR = 8;
    var padT = 18;
    var padB = 18;
    var plotW = PLOT_W - padL - padR;
    var plotH = PLOT_H - padT - padB;

    drawCRTGraticule(ctx, PLOT_W, PLOT_H);

    // Axes
    ctx.save();
    ctx.strokeStyle = '#2a5080';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padL + 0.5, padT);
    ctx.lineTo(padL + 0.5, PLOT_H - padB + 0.5);
    ctx.lineTo(PLOT_W - padR, PLOT_H - padB + 0.5);
    ctx.stroke();

    // Y-axis ticks for log10(Delta) from 0 down to -9
    ctx.font = '8px Courier New, Courier, monospace';
    ctx.fillStyle = '#66aa88';
    ctx.fillText('1e0', 3, padT + 6);
    ctx.fillText('1e-5', 2, padT + Math.round(plotH * 0.55));
    ctx.fillText('1e-9', 2, PLOT_H - padB);
    ctx.fillStyle = '#88bbee';
    ctx.fillText('0', padL - 2, PLOT_H - 5);
    ctx.fillText('k=' + realK, PLOT_W - 28, PLOT_H - 5);

    // Compute max PR across top-5 ego trajectory nodes so traces fill plot cleanly
    var trajNodes = state.subgraph.trajNodes || [];
    var maxPR = 0.004;
    for (var ti = 0; ti < trajNodes.length; ti++) {
      var nIdx = trajNodes[ti].idx;
      for (var k = 0; k <= realK; k++) {
        var v = model.prHistory[k][nIdx];
        if (v > maxPR) maxPR = v;
      }
    }

    // Plot Top-5 ego-node PR trajectories
    for (var j = trajNodes.length - 1; j >= 0; j--) {
      var nodeObj = trajNodes[j];
      var col = TRAJ_COLORS[j % TRAJ_COLORS.length];

      // Faint full curve preview
      ctx.globalAlpha = 0.25;
      ctx.strokeStyle = col;
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (var kf = 0; kf <= realK; kf++) {
        var fx = padL + (kf / K) * plotW;
        var fy = PLOT_H - padB - (model.prHistory[kf][nodeObj.idx] / maxPR) * plotH;
        if (kf === 0) ctx.moveTo(fx, fy);
        else ctx.lineTo(fx, fy);
      }
      ctx.stroke();

      // Active curve up to iterK
      ctx.globalAlpha = j === 0 ? 1.0 : 0.85;
      ctx.lineWidth = j === 0 ? 1.8 : 1.1;
      ctx.beginPath();
      for (var ka = 0; ka <= state.iterK; ka++) {
        var ax = padL + (ka / K) * plotW;
        var ay = PLOT_H - padB - (model.prHistory[ka][nodeObj.idx] / maxPR) * plotH;
        if (ka === 0) ctx.moveTo(ax, ay);
        else ctx.lineTo(ax, ay);
      }
      ctx.stroke();

      // Current marker dot
      var dotX = padL + (state.iterK / K) * plotW;
      var dotY = PLOT_H - padB - (model.prHistory[state.iterK][nodeObj.idx] / maxPR) * plotH;
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.arc(dotX, dotY, j === 0 ? 3 : 2, 0, Math.PI * 2);
      ctx.fill();
    }

    // Plot dashed log10(Delta_k) convergence trace
    function logY(deltaVal) {
      var lv = Math.log(Math.max(1e-10, deltaVal)) / Math.LN10;
      if (lv > 0) lv = 0;
      if (lv < -9.5) lv = -9.5;
      return padT + (-lv / 9.5) * plotH;
    }

    ctx.globalAlpha = 0.95;
    ctx.strokeStyle = '#33ff88';
    ctx.lineWidth = 1.6;
    if (typeof ctx.setLineDash === 'function') ctx.setLineDash([4, 3]);
    ctx.beginPath();
    for (var rk = 1; rk <= realK; rk++) {
      var rx = padL + (rk / K) * plotW;
      var ry = logY(model.residuals[rk]);
      if (rk === 1) ctx.moveTo(rx, ry);
      else ctx.lineTo(rx, ry);
    }
    ctx.stroke();
    if (typeof ctx.setLineDash === 'function') ctx.setLineDash([]);

    // Active vertical cursor at current iterK
    var curX = Math.round(padL + (state.iterK / K) * plotW) + 0.5;
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(curX, padT - 2);
    ctx.lineTo(curX, PLOT_H - padB + 2);
    ctx.stroke();

    if (state.iterK >= 1) {
      var curY = logY(model.residuals[state.iterK]);
      ctx.fillStyle = '#33ff88';
      ctx.beginPath();
      ctx.arc(curX, curY, 3, 0, Math.PI * 2);
      ctx.fill();
    }

    // Header legend
    ctx.fillStyle = '#071228';
    ctx.fillRect(0, 0, PLOT_W, 14);
    ctx.font = 'bold 9px Courier New, Courier, monospace';
    ctx.fillStyle = '#33ff88';
    ctx.fillText('-- log10(Delta)', 4, 10);
    ctx.fillStyle = '#ffcc00';
    ctx.fillText('- PR(k) Top5', 112, 10);
    ctx.restore();
  }

  function renderScrubberCanvas() {
    var canvas = state.dom.scrubCanvas;
    if (!canvas || !state.prModel) return;
    var ctx = canvas.getContext('2d');
    var K = Math.max(1, state.prModel.K);
    var ratio = state.iterK / K;

    ctx.fillStyle = '#c0c0c0';
    ctx.fillRect(0, 0, SCRUB_W, SCRUB_H);

    // Classic Win95 sunken trough
    ctx.fillStyle = '#808080';
    ctx.fillRect(0, 0, SCRUB_W, 1);
    ctx.fillRect(0, 0, 1, SCRUB_H);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, SCRUB_H - 1, SCRUB_W, 1);
    ctx.fillRect(SCRUB_W - 1, 0, 1, SCRUB_H);

    var innerW = SCRUB_W - 6;
    var fillW = Math.round(ratio * innerW);
    var blockW = 8;
    ctx.fillStyle = '#000080';
    for (var x = 3; x < 3 + fillW; x += blockW + 2) {
      var bw = Math.min(blockW, 3 + fillW - x);
      if (bw > 0) ctx.fillRect(x, 3, bw, SCRUB_H - 6);
    }

    // Beveled thumb handle at current position
    var thumbX = 3 + Math.round(ratio * (innerW - 8));
    ctx.fillStyle = '#dcdcdc';
    ctx.fillRect(thumbX, 1, 8, SCRUB_H - 2);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(thumbX, 1, 8, 1);
    ctx.fillRect(thumbX, 1, 1, SCRUB_H - 2);
    ctx.fillStyle = '#404040';
    ctx.fillRect(thumbX, SCRUB_H - 2, 8, 1);
    ctx.fillRect(thumbX + 7, 1, 1, SCRUB_H - 2);
  }

  function updateTelemetryDOM() {
    var model = state.prModel;
    var sg = state.subgraph;
    if (!model || !sg || !state.domBuilt) return;
    var dom = state.dom;
    var k = state.iterK;
    var K = model.K;
    var prVec = model.prHistory[k];
    var targetPR = prVec[sg.targetIdx];
    var targetRank = getRankAtIter(sg.targetIdx, k);
    var resVal = k === 0 ? 'initial (1/N)' : model.residuals[k].toExponential(3);

    dom.iterReadout.innerHTML = 'Iter <b>' + k + '</b> / ' + K;
    dom.telIter.textContent = k + ' / ' + K + (k === K ? ' (Converged)' : '');
    dom.telResidual.textContent = resVal;
    dom.telDamp.textContent = 'd = ' + model.damping.toFixed(2) + ' (1-d = ' + (1 - model.damping).toFixed(2) + ')';
    dom.telPR.textContent = targetPR.toFixed(6);
    dom.telRank.textContent = '#' + targetRank + ' / ' + model.N;
    dom.telDegree.textContent = sg.targetNode.inDeg + ' in / ' + sg.targetNode.outDeg + ' out';

    // Classic 1998 Google green PageRank bar (0..10 scale)
    var pr10 = sg.targetNode.page.pr_score_10;
    if (typeof pr10 !== 'number') {
      pr10 = Math.max(1, Math.min(10, Math.round(Math.log(Math.max(targetPR * model.N, 0.2)) / Math.LN10 * 5 + 4)));
    }
    var maxPRRef = model.maxFinalPR > 0 ? model.maxFinalPR : 0.038;
    var liveRatio = Math.min(1, Math.max(0.04, targetPR / maxPRRef));
    var greenPx = Math.round(liveRatio * 68);
    dom.prBarFill.style.width = greenPx + 'px';
    dom.prBarText.textContent = 'PR ' + pr10 + '/10';

    if (dom.playBtn) {
      dom.playBtn.value = state.iterPlaying ? 'Pause' : 'Play';
    }
    updateHoverBar();
  }

  function updateHoverBar() {
    var dom = state.dom;
    if (!dom.hoverBar || !state.subgraph || !state.prModel) return;
    var idx = state.hoveredNodeIdx !== -1 ? state.hoveredNodeIdx : state.subgraph.targetIdx;
    var node = state.subgraph.nodeByIdx[idx];
    if (!node) return;
    var prVal = state.prModel.prHistory[state.iterK][idx];
    var rank = getRankAtIter(idx, state.iterK);
    var prefix = state.hoveredNodeIdx !== -1 ? 'HOVER: ' : 'INSPECTING: ';
    var extra = (idx !== state.subgraph.targetIdx) ? ' | [Click node to refocus]' : ' | [Center Target Node]';
    dom.hoverBar.innerHTML =
      '<b>' + prefix + '</b>' +
      escapeHtml(truncateStr(node.page.title || node.id, 42)) +
      ' <font face="Courier New, Courier, monospace" size="1">(' +
      'PR=' + prVal.toFixed(5) + ', #' + rank + '/' + state.prModel.N +
      ', in=' + node.inDeg + ', out=' + node.outDeg + ')</font>' +
      '<font color="#000080">' + extra + '</font>';
  }

  function buildViewerUrl(docId) {
    var q = state.searchResponse && state.searchResponse.query ? state.searchResponse.query : '';
    var href = 'viewer.html?id=' + encodeURIComponent(docId);
    if (q) href += '&q=' + encodeURIComponent(q);
    return href;
  }

  function updateTargetCardAndTables() {
    var sg = state.subgraph;
    var model = state.prModel;
    var dom = state.dom;
    if (!sg || !model || !domBuiltCheck()) return;

    var tPage = sg.targetNode.page;
    var qText = state.searchResponse && state.searchResponse.query ? state.searchResponse.query : '';
    var viewerHref = buildViewerUrl(sg.targetNode.id);

    dom.targetHeader.innerHTML =
      '<b>Target:</b> ' + escapeHtml(tPage.title || sg.targetNode.id) +
      ' &nbsp;<font size="1" color="#333333">[' + escapeHtml(tPage.slice || 'web') +
      (tPage.category ? ' / ' + escapeHtml(tPage.category) : '') + ']</font><br>' +
      '<a href="' + escapeHtml(viewerHref) + '" style="color:#006600;text-decoration:underline;">' +
      '<font face="Courier New, Courier, monospace" size="1">' +
      escapeHtml(tPage.url || sg.targetNode.id) + '</font></a>';

    dom.backBtn.style.display = state.historyStack.length > 0 ? 'inline' : 'none';

    // Build Score Breakdown Table (inspected target + top 3 competing search results)
    var rows = [];
    var seenRows = {};
    function pushRow(docId, labelTag) {
      if (!docId || seenRows[docId]) return;
      seenRows[docId] = true;
      var res = state.resultById[docId] || null;
      var page = state.pagesMap[docId] || (res && res.doc) || { id: docId, title: docId, in_degree: 0, pagerank: 0 };
      var idx = model.idToIdx[docId];
      var convPR = idx !== undefined ? model.prHistory[model.K][idx] : (page.pagerank || 0);
      var inDeg = idx !== undefined ? model.inAdj[idx].length : (page.in_degree || 0);
      rows.push({
        id: docId,
        tag: labelTag,
        isTarget: docId === sg.targetNode.id,
        title: page.title || docId,
        titleScore: res && typeof res.titleScore === 'number' ? res.titleScore.toFixed(2) : '--',
        anchorScore: res && typeof res.anchorScore === 'number' ? res.anchorScore.toFixed(2) : '--',
        bodyScore: res && typeof res.bodyScore === 'number' ? res.bodyScore.toFixed(2) : '--',
        irScore: res && typeof res.irScore === 'number' ? res.irScore.toFixed(2) : '--',
        prDisplay: res && typeof res.prScore === 'number' ? (res.prScore.toFixed(2) + ' (' + convPR.toFixed(5) + ')') : convPR.toFixed(5),
        inLinks: inDeg,
        finalScore: res && typeof res.finalScore === 'number' ? res.finalScore.toFixed(2) : '--'
      });
    }

    var targetRes = state.resultById[sg.targetNode.id];
    var targetRankLabel = targetRes ? ('#' + targetRes._rank + ' (Inspected)') : 'Inspected';
    pushRow(sg.targetNode.id, targetRankLabel);

    var srList = (state.searchResponse && Array.isArray(state.searchResponse.results)) ? state.searchResponse.results : [];
    var addedComp = 0;
    for (var s = 0; s < srList.length && addedComp < 3; s++) {
      var rDoc = srList[s] && srList[s].doc;
      if (!rDoc || seenRows[rDoc.id]) continue;
      pushRow(rDoc.id, '#' + (s + 1) + ' Result');
      addedComp++;
    }

    // If no query results exist, show top global PageRank nodes for comparison
    if (rows.length < 4 && state.stats && Array.isArray(state.stats.top_pagerank)) {
      for (var tp = 0; tp < state.stats.top_pagerank.length && rows.length < 4; tp++) {
        var topItem = state.stats.top_pagerank[tp];
        if (topItem && topItem.id && !seenRows[topItem.id]) {
          pushRow(topItem.id, 'Top PR #' + (tp + 1));
        }
      }
    }

    var htmlRows = '';
    for (var ri = 0; ri < rows.length; ri++) {
      var row = rows[ri];
      var bg = row.isTarget ? '#ffffcc' : (ri % 2 === 1 ? '#f4f4f4' : '#ffffff');
      htmlRows +=
        '<tr bgcolor="' + bg + '">' +
        '<td nowrap><font size="1" face="Arial, Helvetica, sans-serif"><b>' + escapeHtml(row.tag) + '</b></font></td>' +
        '<td><font size="1" face="Arial, Helvetica, sans-serif">' +
        '<a href="#g98inspect:' + escapeHtml(row.id) + '" style="color:#0000cc;">' +
        escapeHtml(truncateStr(row.title, 44)) + '</a></font></td>' +
        '<td align="right"><font size="1" face="Courier New, Courier, monospace">' + row.titleScore + '</font></td>' +
        '<td align="right"><font size="1" face="Courier New, Courier, monospace">' + row.anchorScore + '</font></td>' +
        '<td align="right"><font size="1" face="Courier New, Courier, monospace">' + row.bodyScore + '</font></td>' +
        '<td align="right"><font size="1" face="Courier New, Courier, monospace">' + row.irScore + '</font></td>' +
        '<td align="right" nowrap><font size="1" face="Courier New, Courier, monospace">' + row.prDisplay + '</font></td>' +
        '<td align="right"><font size="1" face="Courier New, Courier, monospace">' + row.inLinks + '</font></td>' +
        '<td align="right"><b><font size="1" face="Courier New, Courier, monospace" color="#000080">' + row.finalScore + '</font></b></td>' +
        '</tr>';
    }
    dom.scoreTbody.innerHTML = htmlRows;

    // Top Inbound Anchor Texts + Top Citing Pages
    var anchorRowsHtml = '';
    var topAnchors = Array.isArray(tPage.top_anchors) ? tPage.top_anchors.slice() : [];
    if (topAnchors.length === 0 && sg.inboundCandidates.length > 0) {
      var agg = {};
      for (var ai = 0; ai < sg.inboundCandidates.length; ai++) {
        var atxt = sg.inboundCandidates[ai].anchor;
        if (!atxt) continue;
        agg[atxt] = (agg[atxt] || 0) + 1;
      }
      var keys = Object.keys(agg);
      for (var ki = 0; ki < keys.length; ki++) topAnchors.push({ text: keys[ki], count: agg[keys[ki]] });
    }
    topAnchors.sort(function (a, b) {
      var ma = countTermMatches(a.text, state.queryTerms);
      var mb = countTermMatches(b.text, state.queryTerms);
      if ((mb > 0) !== (ma > 0)) return mb > 0 ? 1 : -1;
      return (b.count || 1) - (a.count || 1);
    });

    for (var ta = 0; ta < Math.min(6, topAnchors.length); ta++) {
      var anc = topAnchors[ta];
      anchorRowsHtml +=
        '<tr><td><font size="1" face="Arial, Helvetica, sans-serif">"' +
        highlightQueryHtml(truncateStr(anc.text, 54), state.queryTerms) +
        '"</font></td><td align="right" nowrap><font size="1" face="Courier New, Courier, monospace">x' +
        (anc.count || 1) + '</font></td></tr>';
    }
    if (!anchorRowsHtml) {
      anchorRowsHtml = '<tr><td colspan="2"><font size="1" color="#666666">No inbound anchor text recorded.</font></td></tr>';
    }
    dom.topAnchorsTbody.innerHTML = anchorRowsHtml;

    var citingHtml = '';
    var cands = sg.inboundCandidates || [];
    for (var ci = 0; ci < Math.min(6, cands.length); ci++) {
      var cItem = cands[ci];
      var srcId = model.nodeIds[cItem.srcIdx];
      var srcPage = state.pagesMap[srcId] || { title: srcId };
      var matchMark = cItem.matchCnt > 0 ? '<font color="#996600"><b>[MATCH]</b></font> ' : '';
      citingHtml +=
        '<tr><td><font size="1" face="Arial, Helvetica, sans-serif">' + matchMark +
        '<a href="#g98inspect:' + escapeHtml(srcId) + '" style="color:#0000cc;">' +
        escapeHtml(truncateStr(srcPage.title || srcId, 32)) + '</a><br>' +
        '<font color="#444444">"' + highlightQueryHtml(truncateStr(cItem.anchor || '(link)', 48), state.queryTerms) + '"</font>' +
        '</font></td><td align="right" valign="top" nowrap><font size="1" face="Courier New, Courier, monospace">+' +
        cItem.contrib.toFixed(5) + '</font></td></tr>';
    }
    if (!citingHtml) {
      citingHtml = '<tr><td colspan="2"><font size="1" color="#666666">No inbound citing pages.</font></td></tr>';
    }
    dom.citingTbody.innerHTML = citingHtml;

    if (dom.queryNote) {
      dom.queryNote.textContent = qText
        ? ('Query: "' + qText + '" -- gold edges carry matching anchor text')
        : 'No active query -- showing top PageRank contributors';
    }
  }

  function domBuiltCheck() {
    return !!(state.domBuilt && state.dom && state.dom.graphCanvas);
  }

  function renderAllFrames() {
    renderGraphCanvas();
    renderPlotCanvas();
    renderScrubberCanvas();
    updateTelemetryDOM();
  }

  function stopLoop() {
    if (state.rafId !== null) {
      cancelAnimationFrame(state.rafId);
      state.rafId = null;
    }
  }

  function tick(nowMs) {
    if (!state.domBuilt || !state.subgraph || !state.prModel) {
      state.rafId = null;
      return;
    }

    var dt = state.lastFrameAt ? Math.min(0.06, (nowMs - state.lastFrameAt) / 1000) : 0.016;
    state.lastFrameAt = nowMs;

    if (state.iterPlaying) {
      if (!state.lastStepAt) state.lastStepAt = nowMs;
      if (nowMs - state.lastStepAt >= STEP_INTERVAL_MS) {
        state.lastStepAt = nowMs;
        if (state.iterK < state.prModel.K) {
          state.iterK++;
          renderPlotCanvas();
          renderScrubberCanvas();
          updateTelemetryDOM();
        } else {
          state.iterPlaying = false;
          updateTelemetryDOM();
        }
      }
    }

    for (var i = 0; i < state.particles.length; i++) {
      var p = state.particles[i];
      p.t = (p.t + p.speed * dt) % 1.0;
    }

    renderGraphCanvas();
    state.rafId = requestAnimationFrame(tick);
  }

  function ensureLoop() {
    if (state.rafId === null && state.domBuilt && state.subgraph) {
      state.lastFrameAt = 0;
      state.lastStepAt = 0;
      state.rafId = requestAnimationFrame(tick);
    }
  }

  function setIteration(newK, keepPlaying) {
    if (!state.prModel) return;
    var k = Math.max(0, Math.min(state.prModel.K, Math.round(newK)));
    state.iterK = k;
    if (!keepPlaying) state.iterPlaying = false;
    renderAllFrames();
  }

  function canvasPoint(canvas, evt) {
    var rect = canvas.getBoundingClientRect();
    var sx = rect.width > 0 ? canvas.width / rect.width : 1;
    var sy = rect.height > 0 ? canvas.height / rect.height : 1;
    return {
      x: (evt.clientX - rect.left) * sx,
      y: (evt.clientY - rect.top) * sy
    };
  }

  function hitTestNode(px, py) {
    if (!state.subgraph || !state.prModel) return -1;
    var nodes = state.subgraph.nodes;
    var prVec = state.prModel.prHistory[state.iterK];
    var bestIdx = -1;
    var bestDist = Infinity;
    for (var i = nodes.length - 1; i >= 0; i--) {
      var n = nodes[i];
      var r = Math.max(12, nodeRadius(prVec[n.idx]) + 4);
      var dx = px - n.x;
      var dy = py - n.y;
      var dist = Math.sqrt(dx * dx + dy * dy);
      if (dist <= r && dist < bestDist) {
        bestDist = dist;
        bestIdx = n.idx;
      }
    }
    return bestIdx;
  }

  function scrubFromEvent(evt) {
    if (!state.prModel || !state.dom.scrubCanvas) return;
    var pt = canvasPoint(state.dom.scrubCanvas, evt);
    var ratio = Math.max(0, Math.min(1, (pt.x - 3) / (SCRUB_W - 6)));
    setIteration(Math.round(ratio * state.prModel.K), false);
  }

  function plotScrubFromEvent(evt) {
    if (!state.prModel || !state.dom.plotCanvas) return;
    var pt = canvasPoint(state.dom.plotCanvas, evt);
    var padL = 28;
    var padR = 8;
    var ratio = Math.max(0, Math.min(1, (pt.x - padL) / (PLOT_W - padL - padR)));
    setIteration(Math.round(ratio * state.prModel.K), false);
  }

  function addWindowListener(type, fn) {
    global.addEventListener(type, fn);
    state.winListeners.push({ type: type, fn: fn });
  }

  function clearWindowListeners() {
    for (var i = 0; i < state.winListeners.length; i++) {
      global.removeEventListener(state.winListeners[i].type, state.winListeners[i].fn);
    }
    state.winListeners = [];
  }

  function buildDOM(containerEl) {
    var btnStyle = 'font-family:Arial,Helvetica,sans-serif;font-size:11px;background-color:#c0c0c0;color:#000000;border-top:2px solid #ffffff;border-left:2px solid #ffffff;border-right:2px solid #404040;border-bottom:2px solid #404040;padding:2px 7px;cursor:pointer;';
    var raisedStyle = 'border-top:2px solid #ffffff;border-left:2px solid #ffffff;border-right:2px solid #808080;border-bottom:2px solid #808080;background-color:#dcdcdc;';
    var sunkenStyle = 'border-top:2px solid #808080;border-left:2px solid #808080;border-right:2px solid #ffffff;border-bottom:2px solid #ffffff;background-color:#060d1f;';

    containerEl.innerHTML =
      '<table width="794" border="0" cellpadding="2" cellspacing="0" align="center" bgcolor="#dcdcdc" style="' + raisedStyle + '">' +
        '<tr><td>' +
          '<table width="100%" border="0" cellpadding="4" cellspacing="0" bgcolor="#000080">' +
            '<tr>' +
              '<td><font face="Arial, Helvetica, sans-serif" size="2" color="#ffffff"><b>Stanford BackRub / Google PageRank Link Graph Inspector (d = 0.85)</b></font></td>' +
              '<td align="right"><font face="Courier New, Courier, monospace" size="1" color="#aaddff">Brin &amp; Page (1998) Power Iteration</font></td>' +
            '</tr>' +
          '</table>' +
        '</td></tr>' +

        '<tr><td>' +
          '<table width="100%" border="0" cellpadding="4" cellspacing="0" bgcolor="#f0f0f0" style="border:1px solid #808080;">' +
            '<tr>' +
              '<td class="g98v-targetHeader"><font face="Arial, Helvetica, sans-serif" size="2">Loading PageRank graph...</font></td>' +
              '<td align="right" valign="middle" nowrap>' +
                '<input type="button" class="g98v-backBtn" value="&lt; Back Node" style="' + btnStyle + 'display:none;"> ' +
                '<input type="button" class="g98v-openNetscapeBtn" value="[Open in Netscape]" style="' + btnStyle + '">' +
              '</td>' +
            '</tr>' +
          '</table>' +
        '</td></tr>' +

        '<tr><td>' +
          '<table width="100%" border="0" cellpadding="4" cellspacing="0" bgcolor="#c0c0c0" style="border-top:1px solid #ffffff;border-bottom:1px solid #808080;">' +
            '<tr>' +
              '<td nowrap>' +
                '<input type="button" class="g98v-playBtn" value="Pause" style="' + btnStyle + 'width:58px;"> ' +
                '<input type="button" class="g98v-stepBtn" value="Step +1" style="' + btnStyle + '"> ' +
                '<input type="button" class="g98v-resetBtn" value="Reset k=0" style="' + btnStyle + '"> ' +
                '<input type="button" class="g98v-endBtn" value="Jump to Converged" style="' + btnStyle + '">' +
              '</td>' +
              '<td align="right" valign="middle" nowrap>' +
                '<font face="Courier New, Courier, monospace" size="1" class="g98v-iterReadout">Iter 0 / 0</font>&nbsp;' +
                '<canvas class="g98v-scrubCanvas" width="' + SCRUB_W + '" height="' + SCRUB_H + '" style="vertical-align:middle;cursor:pointer;"></canvas>' +
              '</td>' +
            '</tr>' +
          '</table>' +
        '</td></tr>' +

        '<tr><td>' +
          '<table width="100%" border="0" cellpadding="3" cellspacing="0">' +
            '<tr valign="top">' +
              '<td width="538">' +
                '<table width="100%" border="0" cellpadding="1" cellspacing="0" style="' + sunkenStyle + '">' +
                  '<tr><td align="center"><canvas class="g98v-graphCanvas" width="' + CANVAS_W + '" height="' + CANVAS_H + '" style="display:block;cursor:pointer;"></canvas></td></tr>' +
                '</table>' +
                '<table width="100%" border="0" cellpadding="3" cellspacing="0" bgcolor="#ececec" style="border:1px solid #808080;margin-top:3px;">' +
                  '<tr><td class="g98v-hoverBar"><font face="Arial, Helvetica, sans-serif" size="1">Hover any node to inspect live PR(k); click node to refocus.</font></td></tr>' +
                  '<tr><td><font face="Courier New, Courier, monospace" size="1" color="#444444" class="g98v-queryNote"></font></td></tr>' +
                '</table>' +
              '</td>' +

              '<td width="248">' +
                '<table width="100%" border="0" cellpadding="2" cellspacing="0" bgcolor="#dcdcdc">' +
                  '<tr><td><font face="Arial, Helvetica, sans-serif" size="1"><b>Convergence Plot (Click/Drag to Scrub)</b></font></td></tr>' +
                  '<tr><td>' +
                    '<table border="0" cellpadding="1" cellspacing="0" style="' + sunkenStyle + '">' +
                      '<tr><td><canvas class="g98v-plotCanvas" width="' + PLOT_W + '" height="' + PLOT_H + '" style="display:block;cursor:pointer;"></canvas></td></tr>' +
                    '</table>' +
                  '</td></tr>' +
                '</table>' +

                '<table width="100%" border="1" bordercolor="#808080" cellpadding="3" cellspacing="0" bgcolor="#ffffff" style="margin-top:4px;border-collapse:collapse;">' +
                  '<tr bgcolor="#000080"><td colspan="2"><font face="Arial, Helvetica, sans-serif" size="1" color="#ffffff"><b>Live Power-Iteration Telemetry</b></font></td></tr>' +
                  '<tr><td><font face="Arial, Helvetica, sans-serif" size="1"><b>Iteration</b></font></td><td align="right"><font face="Courier New, Courier, monospace" size="1" class="g98v-telIter">-</font></td></tr>' +
                  '<tr bgcolor="#f5f5f5"><td><font face="Arial, Helvetica, sans-serif" size="1"><b>L1 Residual &Delta;</b></font></td><td align="right"><font face="Courier New, Courier, monospace" size="1" class="g98v-telResidual">-</font></td></tr>' +
                  '<tr><td><font face="Arial, Helvetica, sans-serif" size="1"><b>Damping</b></font></td><td align="right"><font face="Courier New, Courier, monospace" size="1" class="g98v-telDamp">d = 0.85</font></td></tr>' +
                  '<tr bgcolor="#f5f5f5"><td><font face="Arial, Helvetica, sans-serif" size="1"><b>Target PR(k)</b></font></td><td align="right"><b><font face="Courier New, Courier, monospace" size="1" color="#006600" class="g98v-telPR">-</font></b></td></tr>' +
                  '<tr><td><font face="Arial, Helvetica, sans-serif" size="1"><b>Live Rank</b></font></td><td align="right"><b><font face="Courier New, Courier, monospace" size="1" color="#000080" class="g98v-telRank">-</font></b></td></tr>' +
                  '<tr bgcolor="#f5f5f5"><td><font face="Arial, Helvetica, sans-serif" size="1"><b>Hyperlinks</b></font></td><td align="right"><font face="Courier New, Courier, monospace" size="1" class="g98v-telDegree">-</font></td></tr>' +
                  '<tr>' +
                    '<td><font face="Arial, Helvetica, sans-serif" size="1"><b>Google PR Meter</b></font></td>' +
                    '<td align="right">' +
                      '<table border="0" cellpadding="0" cellspacing="0" align="right">' +
                        '<tr>' +
                          '<td>' +
                            '<table border="0" cellpadding="0" cellspacing="0" width="70" bgcolor="#c0c0c0" style="border:1px solid #404040;">' +
                              '<tr><td height="9" align="left"><div class="g98v-prBarFill" style="width:10px;height:9px;background-color:#008000;"></div></td></tr>' +
                            '</table>' +
                          '</td>' +
                          '<td nowrap>&nbsp;<font face="Courier New, Courier, monospace" size="1" class="g98v-prBarText">PR -/10</font></td>' +
                        '</tr>' +
                      '</table>' +
                    '</td>' +
                  '</tr>' +
                '</table>' +
              '</td>' +
            '</tr>' +
          '</table>' +
        '</td></tr>' +

        '<tr><td>' +
          '<table width="100%" border="1" bordercolor="#808080" cellpadding="3" cellspacing="0" bgcolor="#ffffff" style="border-collapse:collapse;">' +
            '<tr bgcolor="#000080"><td colspan="9"><font face="Arial, Helvetica, sans-serif" size="1" color="#ffffff"><b>1998 Ranking Score Breakdown (Inspected Result &amp; Top Competitors -- Click Row to Inspect)</b></font></td></tr>' +
            '<tr bgcolor="#c0c0c0">' +
              '<td><font face="Arial, Helvetica, sans-serif" size="1"><b>Result</b></font></td>' +
              '<td><font face="Arial, Helvetica, sans-serif" size="1"><b>Page Title</b></font></td>' +
              '<td align="right"><font face="Arial, Helvetica, sans-serif" size="1"><b>Title Score</b></font></td>' +
              '<td align="right"><font face="Arial, Helvetica, sans-serif" size="1"><b>Anchor Score</b></font></td>' +
              '<td align="right"><font face="Arial, Helvetica, sans-serif" size="1"><b>Body IR</b></font></td>' +
              '<td align="right"><font face="Arial, Helvetica, sans-serif" size="1"><b>Combined IR</b></font></td>' +
              '<td align="right"><font face="Arial, Helvetica, sans-serif" size="1"><b>PageRank Score</b></font></td>' +
              '<td align="right"><font face="Arial, Helvetica, sans-serif" size="1"><b>In-Links</b></font></td>' +
              '<td align="right"><font face="Arial, Helvetica, sans-serif" size="1"><b>Total Score</b></font></td>' +
            '</tr>' +
            '<tbody class="g98v-scoreTbody"></tbody>' +
          '</table>' +
        '</td></tr>' +

        '<tr><td>' +
          '<table width="100%" border="0" cellpadding="0" cellspacing="4">' +
            '<tr valign="top">' +
              '<td width="46%">' +
                '<table width="100%" border="1" bordercolor="#808080" cellpadding="3" cellspacing="0" bgcolor="#ffffff" style="border-collapse:collapse;">' +
                  '<tr bgcolor="#000080"><td colspan="2"><font face="Arial, Helvetica, sans-serif" size="1" color="#ffffff"><b>Top Inbound Anchor Texts</b></font></td></tr>' +
                  '<tbody class="g98v-topAnchorsTbody"></tbody>' +
                '</table>' +
              '</td>' +
              '<td width="54%">' +
                '<table width="100%" border="1" bordercolor="#808080" cellpadding="3" cellspacing="0" bgcolor="#ffffff" style="border-collapse:collapse;">' +
                  '<tr bgcolor="#000080"><td colspan="2"><font face="Arial, Helvetica, sans-serif" size="1" color="#ffffff"><b>Top Citing Pages &amp; Rank Transfer (Click to Refocus)</b></font></td></tr>' +
                  '<tbody class="g98v-citingTbody"></tbody>' +
                '</table>' +
              '</td>' +
            '</tr>' +
          '</table>' +
        '</td></tr>' +
      '</table>';

    var roleNames = [
      'targetHeader', 'backBtn', 'openNetscapeBtn', 'playBtn', 'stepBtn',
      'resetBtn', 'endBtn', 'iterReadout', 'scrubCanvas', 'graphCanvas',
      'hoverBar', 'queryNote', 'plotCanvas', 'telIter', 'telResidual',
      'telDamp', 'telPR', 'telRank', 'telDegree', 'prBarFill', 'prBarText',
      'scoreTbody', 'topAnchorsTbody', 'citingTbody'
    ];
    var dom = {};
    for (var i = 0; i < roleNames.length; i++) {
      var rName = roleNames[i];
      dom[rName] = containerEl.querySelector('.g98v-' + rName);
    }
    state.dom = dom;
    state.domBuilt = true;

    dom.playBtn.addEventListener('click', function () {
      if (!state.prModel) return;
      if (!state.iterPlaying) {
        if (state.iterK >= state.prModel.K) state.iterK = 0;
        state.iterPlaying = true;
        state.lastStepAt = 0;
        ensureLoop();
      } else {
        state.iterPlaying = false;
      }
      updateTelemetryDOM();
    });

    dom.stepBtn.addEventListener('click', function () {
      if (!state.prModel) return;
      state.iterPlaying = false;
      setIteration(Math.min(state.prModel.K, state.iterK + 1), false);
    });

    dom.resetBtn.addEventListener('click', function () {
      state.iterPlaying = false;
      setIteration(0, false);
    });

    dom.endBtn.addEventListener('click', function () {
      if (!state.prModel) return;
      state.iterPlaying = false;
      setIteration(state.prModel.K, false);
    });

    dom.backBtn.addEventListener('click', function () {
      if (!state.historyStack.length) return;
      var prevId = state.historyStack.pop();
      inspectInternal(prevId, state.searchResponse, true);
    });

    dom.openNetscapeBtn.addEventListener('click', function () {
      if (!state.targetId) return;
      global.location.href = buildViewerUrl(state.targetId);
    });

    dom.graphCanvas.addEventListener('mousemove', function (evt) {
      var pt = canvasPoint(dom.graphCanvas, evt);
      var hit = hitTestNode(pt.x, pt.y);
      if (hit !== state.hoveredNodeIdx) {
        state.hoveredNodeIdx = hit;
        dom.graphCanvas.style.cursor = hit !== -1 ? 'pointer' : 'default';
        updateHoverBar();
        renderGraphCanvas();
      }
    });

    dom.graphCanvas.addEventListener('mouseleave', function () {
      dom.graphCanvas.style.cursor = 'default';
      if (state.hoveredNodeIdx !== -1) {
        state.hoveredNodeIdx = -1;
        updateHoverBar();
        renderGraphCanvas();
      }
    });

    dom.graphCanvas.addEventListener('click', function (evt) {
      if (!state.subgraph) return;
      var pt = canvasPoint(dom.graphCanvas, evt);
      var hit = hitTestNode(pt.x, pt.y);
      if (hit === -1) return;
      var clickedId = state.prModel.nodeIds[hit];
      if (clickedId === state.subgraph.targetNode.id) {
        global.location.href = buildViewerUrl(clickedId);
      } else {
        inspectInternal(clickedId, state.searchResponse, false);
      }
    });

    dom.scrubCanvas.addEventListener('mousedown', function (evt) {
      state.scrubDragging = 'scrub';
      scrubFromEvent(evt);
    });

    dom.plotCanvas.addEventListener('mousedown', function (evt) {
      state.scrubDragging = 'plot';
      plotScrubFromEvent(evt);
    });

    clearWindowListeners();
    addWindowListener('mousemove', function (evt) {
      if (!state.scrubDragging) return;
      if (state.scrubDragging === 'scrub') scrubFromEvent(evt);
      else if (state.scrubDragging === 'plot') plotScrubFromEvent(evt);
    });
    addWindowListener('mouseup', function () {
      state.scrubDragging = false;
    });

    // Delegate click on score breakdown & citing links to refocus inspector
    if (state.containerClickHandler) {
      containerEl.removeEventListener('click', state.containerClickHandler);
    }
    state.containerClickHandler = function (evt) {
      var el = evt.target;
      while (el && el !== containerEl) {
        if (el.tagName === 'A' && el.getAttribute) {
          var href = el.getAttribute('href') || '';
          if (href.indexOf('#g98inspect:') === 0) {
            evt.preventDefault();
            var id = href.slice('#g98inspect:'.length);
            inspectInternal(id, state.searchResponse, false);
            return;
          }
        }
        el = el.parentNode;
      }
    };
    containerEl.addEventListener('click', state.containerClickHandler);
  }

  function inspectInternal(targetDocId, searchResponse, skipHistory) {
    if (!state.dataReady || !state.prModel) {
      state.pendingInspect = { targetDocId: targetDocId, searchResponse: searchResponse };
      ensureData().then(function () {
        if (state.pendingInspect) {
          var pending = state.pendingInspect;
          state.pendingInspect = null;
          inspectInternal(pending.targetDocId, pending.searchResponse, false);
        }
      });
      return;
    }

    var resolvedId = resolveTargetId(targetDocId, searchResponse);
    if (!skipHistory && state.targetId && state.targetId !== resolvedId) {
      state.historyStack.push(state.targetId);
      if (state.historyStack.length > 20) state.historyStack.shift();
    } else if (!state.targetId) {
      state.historyStack = [];
    }

    state.targetId = resolvedId;
    state.searchResponse = searchResponse || null;
    state.queryTerms = extractQueryTerms(searchResponse);
    state.resultById = {};
    if (searchResponse && Array.isArray(searchResponse.results)) {
      for (var i = 0; i < searchResponse.results.length; i++) {
        var r = searchResponse.results[i];
        if (r && r.doc && r.doc.id) {
          r._rank = i + 1;
          state.resultById[r.doc.id] = r;
        }
      }
    }

    if (!state.domBuilt && state.containerEl) {
      buildDOM(state.containerEl);
    }

    state.subgraph = buildSubgraph(resolvedId, state.searchResponse, state.queryTerms);
    state.hoveredNodeIdx = -1;
    state.iterK = 0;
    state.iterPlaying = true;
    state.lastStepAt = 0;
    spawnParticles(state.subgraph);

    if (state.domBuilt) {
      updateTargetCardAndTables();
      renderAllFrames();
      ensureLoop();
    }
  }

  function init(containerEl) {
    if (!containerEl) return;
    if (state.containerEl && state.containerEl !== containerEl) {
      destroy();
    }
    state.containerEl = containerEl;
    if (!state.domBuilt) {
      buildDOM(containerEl);
    }
    ensureData().then(function () {
      if (!state.domBuilt) return;
      if (state.pendingInspect) {
        var pending = state.pendingInspect;
        state.pendingInspect = null;
        inspectInternal(pending.targetDocId, pending.searchResponse, false);
      } else if (!state.subgraph) {
        inspectInternal(state.targetId, state.searchResponse, true);
      } else {
        renderAllFrames();
        ensureLoop();
      }
    });
  }

  function inspect(targetDocId, searchResponse) {
    var normResp = searchResponse || null;
    if (state.targetId && normResp !== state.searchResponse) {
      state.historyStack = [];
      state.targetId = null;
    }
    inspectInternal(targetDocId, normResp, false);
  }

  function pause() {
    stopLoop();
    state.iterPlaying = false;
    if (state.domBuilt && state.dom.playBtn) {
      state.dom.playBtn.value = 'Play';
    }
  }

  function destroy() {
    stopLoop();
    clearWindowListeners();
    if (state.containerEl && state.containerClickHandler) {
      state.containerEl.removeEventListener('click', state.containerClickHandler);
      state.containerClickHandler = null;
    }
    state.iterPlaying = false;
    state.domBuilt = false;
    state.dom = {};
    state.subgraph = null;
    state.particles = [];
    state.hoveredNodeIdx = -1;
    state.pendingInspect = null;
    state.historyStack = [];
    state.targetId = null;
    if (state.containerEl) {
      state.containerEl.innerHTML = '';
      state.containerEl = null;
    }
  }

  global.Google98Viz = {
    init: init,
    inspect: inspect,
    pause: pause,
    destroy: destroy
  };
})(window);
