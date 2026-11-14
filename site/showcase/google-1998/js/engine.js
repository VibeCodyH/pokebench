/* 1998 Google Search Engine Simulation - Client-Side Ranking & Retrieval
 * Exposes window.Google98Engine
 * Classic ES5-compatible browser JavaScript, zero external dependencies.
 */
(function (root) {
  "use strict";

  var STOPWORDS = {
    "a": 1, "an": 1, "and": 1, "are": 1, "as": 1, "at": 1, "be": 1, "been": 1,
    "but": 1, "by": 1, "can": 1, "do": 1, "for": 1, "from": 1, "had": 1, "has": 1,
    "have": 1, "he": 1, "her": 1, "here": 1, "his": 1, "if": 1, "in": 1, "into": 1,
    "is": 1, "it": 1, "its": 1, "just": 1, "like": 1, "make": 1, "me": 1, "more": 1,
    "my": 1, "no": 1, "not": 1, "of": 1, "on": 1, "one": 1, "or": 1, "our": 1,
    "out": 1, "over": 1, "she": 1, "so": 1, "some": 1, "such": 1, "than": 1,
    "that": 1, "the": 1, "their": 1, "them": 1, "then": 1, "there": 1, "these": 1,
    "they": 1, "this": 1, "to": 1, "up": 1, "was": 1, "we": 1, "what": 1,
    "when": 1, "where": 1, "which": 1, "who": 1, "will": 1, "with": 1, "would": 1,
    "you": 1, "your": 1, "also": 1, "about": 1
  };

  var STEM_PROTECT = {
    "news": 1, "series": 1, "species": 1, "emacs": 1, "cics": 1, "egcs": 1,
    "geocities": 1, "webring": 1, "sterling": 1, "spring": 1, "string": 1,
    "nothing": 1, "something": 1, "anything": 1, "everything": 1, "morning": 1,
    "evening": 1, "ceiling": 1, "bowling": 1, "viking": 1, "herring": 1,
    "embed": 1, "hundred": 1, "sacred": 1, "naked": 1, "wicked": 1,
    "solaris": 1, "borealis": 1, "bios": 1, "linux": 1, "atlas": 1, "fritos": 1
  };

  var IRREGULAR_STEMS = {
    "cookies": "cookie",
    "movies": "movie"
  };

  var _isReady = false;
  var _readyPromise = null;
  var _pagesList = [];
  var _pagesMap = {};
  var _urlMap = {};
  var _index = null;
  var _graph = null;
  var _stats = null;
  var _inboundByDoc = {};
  var _minPr = 0.0003;
  var _maxPr = 0.02;
  var _logMinPr = Math.log(0.0003);
  var _logSpanPr = 1.0;

  function endsWith(str, suffix) {
    if (str.length < suffix.length) return false;
    return str.slice(str.length - suffix.length) === suffix;
  }

  function hasVowel(str) {
    return /[aeiouy]/.test(str);
  }

  function stemToken(w) {
    if (Object.prototype.hasOwnProperty.call(IRREGULAR_STEMS, w)) {
      return IRREGULAR_STEMS[w];
    }
    if (w.length <= 3 || Object.prototype.hasOwnProperty.call(STEM_PROTECT, w)) {
      return w;
    }
    if (/[0-9]/.test(w)) {
      return w;
    }

    if (endsWith(w, "ies") && w.length > 4) {
      w = w.slice(0, -3) + "y";
    } else if (endsWith(w, "sses") && w.length > 5) {
      w = w.slice(0, -2);
    } else if ((endsWith(w, "xes") || endsWith(w, "ches") || endsWith(w, "shes")) && w.length > 4) {
      w = w.slice(0, -2);
    } else if (endsWith(w, "s") && !endsWith(w, "ss") && !endsWith(w, "us") && !endsWith(w, "is") && !endsWith(w, "os")) {
      w = w.slice(0, -1);
    }

    var s, last, prev;
    if (endsWith(w, "ing") && w.length > 5) {
      s = w.slice(0, -3);
      if (s.length >= 3 && hasVowel(s)) {
        last = s.charAt(s.length - 1);
        prev = s.charAt(s.length - 2);
        if (s.length >= 4 && last === prev && last !== "l" && last !== "s" && last !== "f" && last !== "z") {
          s = s.slice(0, -1);
        }
        w = s;
      }
    } else if (endsWith(w, "ied") && w.length > 4) {
      w = w.slice(0, -3) + "y";
    } else if (endsWith(w, "ed") && w.length > 4 && !endsWith(w, "eed")) {
      s = w.slice(0, -2);
      if (s.length >= 3 && hasVowel(s)) {
        last = s.charAt(s.length - 1);
        prev = s.charAt(s.length - 2);
        if (s.length >= 4 && last === prev && last !== "l" && last !== "s" && last !== "f" && last !== "z") {
          s = s.slice(0, -1);
        }
        w = s;
      }
    }
    return w;
  }

  function tokenize(text) {
    if (!text) return [];
    var matches = String(text).toLowerCase().match(/[a-z0-9]+/g);
    if (!matches) return [];
    var out = [];
    for (var i = 0; i < matches.length; i++) {
      var tok = matches[i];
      if (tok.length < 2 && tok !== "c") continue;
      if (Object.prototype.hasOwnProperty.call(STOPWORDS, tok)) continue;
      if (/^\d+$/.test(tok) && (tok.length > 6 || (tok.length >= 4 && tok.charAt(0) === "0"))) continue;
      if (tok.length > 36) continue;
      var stemmed = stemToken(tok);
      if (Object.prototype.hasOwnProperty.call(STOPWORDS, stemmed)) continue;
      out.push(stemmed);
    }
    return out;
  }

  function tokenizeRaw(text) {
    if (!text) return [];
    var matches = String(text).toLowerCase().match(/[a-z0-9]+/g);
    if (!matches) return [];
    var out = [];
    for (var i = 0; i < matches.length; i++) {
      var tok = matches[i];
      if (tok.length > 0 && tok.length <= 36) {
        out.push(tok);
      }
    }
    return out;
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function normalizeUrlKey(rawUrl) {
    if (!rawUrl) return "";
    var u = String(rawUrl).replace(/^\s+|\s+$/g, "");
    var hashIdx = u.indexOf("#");
    if (hashIdx !== -1) u = u.slice(0, hashIdx);
    var qIdx = u.indexOf("?");
    if (qIdx !== -1) u = u.slice(0, qIdx);
    u = u.toLowerCase();
    u = u.replace(/:80(\/|$)/, "$1");
    return u;
  }

  function registerUrlVariants(doc) {
    var u = normalizeUrlKey(doc.url);
    if (u) {
      _urlMap[u] = doc;
      if (endsWith(u, "/index.html")) {
        var dirUrl = u.slice(0, -10);
        _urlMap[dirUrl] = doc;
        _urlMap[dirUrl.slice(0, -1)] = doc;
      }
      if (u.indexOf("http://") === 0) {
        var noScheme = u.slice(7);
        _urlMap[noScheme] = doc;
        if (endsWith(noScheme, "/index.html")) {
          var noSchemeDir = noScheme.slice(0, -10);
          _urlMap[noSchemeDir] = doc;
          _urlMap[noSchemeDir.slice(0, -1)] = doc;
        }
      }
    }
    if (doc.path) {
      var p = String(doc.path).toLowerCase();
      _urlMap[p] = doc;
    }
  }

  function initFromPayloads(pagesData, indexData, graphData, statsData) {
    _pagesList = (pagesData && pagesData.pages) ? pagesData.pages : [];
    _pagesMap = {};
    _urlMap = {};
    _inboundByDoc = {};

    var i;
    var minP = Infinity;
    var maxP = 0;

    for (i = 0; i < _pagesList.length; i++) {
      var doc = _pagesList[i];
      _pagesMap[doc.id] = doc;
      registerUrlVariants(doc);
      var prVal = (typeof doc.pagerank === "number" && doc.pagerank > 0) ? doc.pagerank : 0.0001;
      if (prVal < minP) minP = prVal;
      if (prVal > maxP) maxP = prVal;
    }

    if (!isFinite(minP) || minP <= 0) minP = 0.0003;
    if (maxP <= minP) maxP = minP * 10;
    _minPr = minP;
    _maxPr = maxP;
    _logMinPr = Math.log(_minPr);
    _logSpanPr = Math.log(_maxPr) - _logMinPr;
    if (_logSpanPr <= 0) _logSpanPr = 1.0;

    _index = indexData || { doc_count: _pagesList.length, avg_doc_len: 100, terms: {} };
    _graph = graphData || { damping: 0.85, num_pages: _pagesList.length, edges: [] };
    _stats = statsData || { corpus_pages: _pagesList.length };

    var edges = _graph.edges || [];
    for (i = 0; i < edges.length; i++) {
      var e = edges[i];
      var srcId = e[0];
      var tgtId = e[1];
      var ancText = e[2] || "";
      var srcDoc = _pagesMap[srcId];
      if (!Object.prototype.hasOwnProperty.call(_inboundByDoc, tgtId)) {
        _inboundByDoc[tgtId] = [];
      }
      _inboundByDoc[tgtId].push({
        source_id: srcId,
        source_title: srcDoc ? srcDoc.title : srcId,
        source_url: srcDoc ? srcDoc.url : "",
        source_pr: srcDoc ? (srcDoc.pagerank || 0) : 0,
        anchor_text: ancText
      });
    }

    _isReady = true;
  }

  function fetchJson(url) {
    if (typeof fetch === "function") {
      return fetch(url).then(function (resp) {
        if (!resp.ok) {
          throw new Error("HTTP " + resp.status + " fetching " + url);
        }
        return resp.json();
      });
    }
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open("GET", url, true);
      xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              resolve(JSON.parse(xhr.responseText));
            } catch (err) {
              reject(err);
            }
          } else {
            reject(new Error("HTTP " + xhr.status + " fetching " + url));
          }
        }
      };
      xhr.send();
    });
  }

  function ready() {
    if (_isReady) {
      return Promise.resolve();
    }
    if (_readyPromise) {
      return _readyPromise;
    }

    var gData = (typeof root !== "undefined") ? root.GOOGLE98_DATA : null;
    if (gData && gData.pages && gData.index && gData.graph && gData.stats) {
      initFromPayloads(gData.pages, gData.index, gData.graph, gData.stats);
      _readyPromise = Promise.resolve();
      return _readyPromise;
    }

    _readyPromise = Promise.all([
      fetchJson("data/pages.json"),
      fetchJson("data/index.json"),
      fetchJson("data/graph.json"),
      fetchJson("data/stats.json")
    ]).then(function (results) {
      initFromPayloads(results[0], results[1], results[2], results[3]);
    });
    return _readyPromise;
  }

  function getPageById(id) {
    if (!id) return null;
    return Object.prototype.hasOwnProperty.call(_pagesMap, id) ? _pagesMap[id] : null;
  }

  function getPageByUrl(url) {
    if (!url) return null;
    var norm = normalizeUrlKey(url);
    if (!norm) return null;
    if (Object.prototype.hasOwnProperty.call(_urlMap, norm)) {
      return _urlMap[norm];
    }
    var trimmed = norm.replace(/\/+$/, "");
    if (Object.prototype.hasOwnProperty.call(_urlMap, trimmed)) {
      return _urlMap[trimmed];
    }
    if (Object.prototype.hasOwnProperty.call(_urlMap, trimmed + "/index.html")) {
      return _urlMap[trimmed + "/index.html"];
    }
    if (norm.indexOf("http://") !== 0 && norm.indexOf("https://") !== 0) {
      var withHttp = "http://" + trimmed;
      if (Object.prototype.hasOwnProperty.call(_urlMap, withHttp)) {
        return _urlMap[withHttp];
      }
      if (Object.prototype.hasOwnProperty.call(_urlMap, withHttp + "/index.html")) {
        return _urlMap[withHttp + "/index.html"];
      }
    }
    return null;
  }

  function getSimilarPages(id) {
    var doc = getPageById(id);
    if (!doc || !doc.similar_ids) return [];
    var out = [];
    for (var i = 0; i < doc.similar_ids.length; i++) {
      var sim = getPageById(doc.similar_ids[i]);
      if (sim) out.push(sim);
    }
    return out;
  }

  function getStats() {
    return _stats;
  }

  function getGraph() {
    return _graph;
  }

  function getPagesMap() {
    return _pagesMap;
  }

  function parseQueryAndFilters(queryStr, options) {
    var opts = options || {};
    var filterSlice = opts.filterSlice ? String(opts.filterSlice).toLowerCase().replace(/^\s+|\s+$/g, "") : "";
    var filterDomain = opts.filterDomain ? String(opts.filterDomain).toLowerCase().replace(/^\s+|\s+$/g, "") : "";

    var rawQ = (queryStr === null || queryStr === undefined) ? "" : String(queryStr);
    var cleanedParts = [];
    var parts = rawQ.split(/\s+/);
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i];
      if (!part) continue;
      var low = part.toLowerCase();
      if (low.indexOf("site:") === 0 && part.length > 5) {
        if (!filterDomain) {
          filterDomain = low.slice(5);
        }
      } else if (low.indexOf("slice:") === 0 && part.length > 6) {
        if (!filterSlice) {
          filterSlice = low.slice(6);
        }
      } else {
        cleanedParts.push(part);
      }
    }

    return {
      cleanQuery: cleanedParts.join(" "),
      filterSlice: filterSlice,
      filterDomain: filterDomain
    };
  }

  function docMatchesFilters(doc, filterSlice, filterDomain) {
    if (filterSlice && (!doc.slice || doc.slice.toLowerCase() !== filterSlice)) {
      return false;
    }
    if (filterDomain) {
      var urlLow = (doc.url || "").toLowerCase();
      var noProto = urlLow.replace(/^https?:\/\//, "");
      var slashIdx = noProto.indexOf("/");
      var host = (slashIdx === -1) ? noProto : noProto.slice(0, slashIdx);
      var fd = filterDomain.replace(/^https?:\/\//, "").replace(/\/+$/, "");

      if (fd.indexOf("/") !== -1) {
        var fdNoWww = fd.replace(/^www\./, "");
        var pathNoWww = noProto.replace(/^www\./, "");
        if (noProto.indexOf(fd) !== 0 && pathNoWww.indexOf(fdNoWww) !== 0) {
          return false;
        }
      } else {
        var hostNoWww = host.replace(/^www\./, "");
        var fdBare = fd.replace(/^www\./, "");
        if (host !== fd && !endsWith(host, "." + fd) && hostNoWww !== fdBare) {
          return false;
        }
      }
    }
    return true;
  }

  function computePrMultiplier(doc) {
    var pr = (typeof doc.pagerank === "number" && doc.pagerank > _minPr) ? doc.pagerank : _minPr;
    var norm = (Math.log(pr) - _logMinPr) / _logSpanPr;
    if (norm < 0) norm = 0;
    if (norm > 1) norm = 1;
    return 1.0 + 2.5 * norm;
  }

  function hasPhraseInTokens(haystackTokens, needleTokens) {
    var m = needleTokens.length;
    if (m < 2 || haystackTokens.length < m) return false;
    for (var i = 0; i <= haystackTokens.length - m; i++) {
      var ok = true;
      for (var j = 0; j < m; j++) {
        if (haystackTokens[i + j] !== needleTokens[j]) {
          ok = false;
          break;
        }
      }
      if (ok) return true;
    }
    return false;
  }

  function countAdjacentPairsInTokens(haystackTokens, needleTokens) {
    if (needleTokens.length < 2 || haystackTokens.length < 2) return 0;
    var pairHits = 0;
    for (var p = 0; p < needleTokens.length - 1; p++) {
      var a = needleTokens[p];
      var b = needleTokens[p + 1];
      for (var i = 0; i < haystackTokens.length - 1; i++) {
        if (haystackTokens[i] === a && haystackTokens[i + 1] === b) {
          pairHits += 1;
          break;
        }
      }
    }
    return pairHits;
  }

  function highlightTextHtml(text, queryTermSet, rawMode) {
    if (!text) return "";
    var chunks = String(text).match(/[A-Za-z0-9]+|[^A-Za-z0-9]+/g);
    if (!chunks) return escapeHtml(text);

    var out = [];
    for (var i = 0; i < chunks.length; i++) {
      var ch = chunks[i];
      if (/^[A-Za-z0-9]+$/.test(ch)) {
        var low = ch.toLowerCase();
        var key = rawMode ? low : stemToken(low);
        var isStop = !rawMode && Object.prototype.hasOwnProperty.call(STOPWORDS, low);
        if (!isStop && Object.prototype.hasOwnProperty.call(queryTermSet, key)) {
          out.push("<b>" + escapeHtml(ch) + "</b>");
        } else {
          out.push(escapeHtml(ch));
        }
      } else {
        out.push(escapeHtml(ch));
      }
    }
    return out.join("");
  }

  function buildSnippetHtml(doc, queryTermSet, matchedAnchors, tScore, aScore, bScore, rawMode) {
    var body = doc.body_text || doc.excerpt || "";
    var windowLen = 210;
    var snippetText = "";

    if (body) {
      var wordRe = /[A-Za-z0-9]+/g;
      var match;
      var hits = [];
      while ((match = wordRe.exec(body)) !== null) {
        var low = match[0].toLowerCase();
        if (!rawMode && Object.prototype.hasOwnProperty.call(STOPWORDS, low)) continue;
        var norm = rawMode ? low : stemToken(low);
        if (Object.prototype.hasOwnProperty.call(queryTermSet, norm)) {
          hits.push({
            pos: match.index,
            end: match.index + match[0].length,
            term: norm
          });
        }
      }

      if (hits.length > 0 && body.length > windowLen) {
        var bestScore = -1;
        var bestStart = 0;
        for (var i = 0; i < hits.length; i++) {
          var anchorPos = hits[i].pos;
          var winStart = Math.max(0, anchorPos - 55);
          var winEnd = winStart + windowLen;
          var distinct = {};
          var distinctCnt = 0;
          var totalCnt = 0;
          for (var j = i; j < hits.length && hits[j].pos < winEnd; j++) {
            totalCnt += 1;
            if (!Object.prototype.hasOwnProperty.call(distinct, hits[j].term)) {
              distinct[hits[j].term] = 1;
              distinctCnt += 1;
            }
          }
          var score = distinctCnt * 10 + totalCnt;
          if (score > bestScore) {
            bestScore = score;
            bestStart = winStart;
          }
        }

        // Snap start to word boundary
        if (bestStart > 0) {
          var nextSpace = body.indexOf(" ", bestStart);
          if (nextSpace !== -1 && nextSpace - bestStart < 18) {
            bestStart = nextSpace + 1;
          }
        }
        var bestEnd = Math.min(body.length, bestStart + windowLen);
        if (bestEnd < body.length) {
          var lastSpace = body.lastIndexOf(" ", bestEnd);
          if (lastSpace > bestStart + 80) {
            bestEnd = lastSpace;
          }
        }
        snippetText = (bestStart > 0 ? "..." : "") + body.slice(bestStart, bestEnd) + (bestEnd < body.length ? "..." : "");
      } else {
        snippetText = body.length > windowLen ? (body.slice(0, windowLen).replace(/\s+\S*$/, "") + "...") : body;
      }
    }

    var bodyHtml = highlightTextHtml(snippetText, queryTermSet, rawMode);

    // If matched primarily via inbound anchor text, highlight the best anchor callout right inside snippetHtml
    var primarilyAnchor = matchedAnchors && matchedAnchors.length > 0 &&
      (bScore <= 0.01 || aScore > (tScore + bScore) * 0.9);
    if (primarilyAnchor) {
      var bestAnc = matchedAnchors[0].anchor_text || "";
      var ancHighlighted = highlightTextHtml(bestAnc, queryTermSet, rawMode);
      return '[Inbound anchor match: "' + ancHighlighted + '"] ' + bodyHtml;
    }

    return bodyHtml;
  }

  function runRawStopwordFallback(rawWords, filterSlice, filterDomain) {
    var uniqueRaw = [];
    var seen = {};
    var termSet = {};
    var i;
    for (i = 0; i < rawWords.length; i++) {
      var rw = rawWords[i];
      if (!Object.prototype.hasOwnProperty.call(seen, rw)) {
        seen[rw] = 1;
        uniqueRaw.push(rw);
        termSet[rw] = 1;
      }
    }

    var scored = [];
    for (i = 0; i < _pagesList.length; i++) {
      var doc = _pagesList[i];
      if (!docMatchesFilters(doc, filterSlice, filterDomain)) continue;
      var tToks = tokenizeRaw(doc.title);
      var bToks = tokenizeRaw(doc.body_text);
      var tSet = {};
      var bSet = {};
      var j;
      for (j = 0; j < tToks.length; j++) tSet[tToks[j]] = (tSet[tToks[j]] || 0) + 1;
      for (j = 0; j < bToks.length; j++) bSet[bToks[j]] = (bSet[bToks[j]] || 0) + 1;

      var tHits = 0;
      var bHits = 0;
      var matched = [];
      for (j = 0; j < uniqueRaw.length; j++) {
        var term = uniqueRaw[j];
        var tc = tSet[term] || 0;
        var bc = bSet[term] || 0;
        if (tc > 0 || bc > 0) {
          matched.push(term);
          tHits += tc * 2.5;
          bHits += Math.min(bc, 5) * 0.8;
        }
      }
      if (matched.length === 0) continue;
      var coord = Math.pow(matched.length / uniqueRaw.length, 2.0);
      var tScore = tHits * coord;
      var bScore = bHits * coord;
      var irScore = tScore + bScore;
      var prScore = computePrMultiplier(doc);
      var finalScore = irScore * prScore;

      scored.push({
        doc: doc,
        finalScore: Math.round(finalScore * 100) / 100,
        irScore: Math.round(irScore * 100) / 100,
        titleScore: Math.round(tScore * 100) / 100,
        anchorScore: 0,
        bodyScore: Math.round(bScore * 100) / 100,
        prScore: Math.round(prScore * 100) / 100,
        matchedTerms: matched,
        matchedAnchors: [],
        snippetHtml: buildSnippetHtml(doc, termSet, [], tScore, 0, bScore, true)
      });
    }

    scored.sort(function (a, b) {
      if (b.finalScore !== a.finalScore) return b.finalScore - a.finalScore;
      if ((b.doc.pagerank || 0) !== (a.doc.pagerank || 0)) return (b.doc.pagerank || 0) - (a.doc.pagerank || 0);
      return a.doc.id < b.doc.id ? -1 : (a.doc.id > b.doc.id ? 1 : 0);
    });
    return { terms: uniqueRaw, scored: scored };
  }

  function search(query, options) {
    var t0 = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
    var opts = options || {};
    var parsed = parseQueryAndFilters(query, opts);
    var cleanQuery = parsed.cleanQuery;
    var filterSlice = parsed.filterSlice;
    var filterDomain = parsed.filterDomain;

    if (!_isReady) {
      return {
        query: query || "",
        terms: [],
        totalResults: 0,
        elapsedSec: "0.00",
        results: []
      };
    }

    var offset = (typeof opts.offset === "number" && opts.offset >= 0) ? Math.floor(opts.offset) : 0;
    var hasLimit = (typeof opts.limit === "number" && opts.limit >= 0);
    var limit = hasLimit ? Math.floor(opts.limit) : null;

    var rawTerms = tokenize(cleanQuery);
    var uniqueTerms = [];
    var termSet = {};
    var i, j;
    for (i = 0; i < rawTerms.length; i++) {
      if (!Object.prototype.hasOwnProperty.call(termSet, rawTerms[i])) {
        termSet[rawTerms[i]] = 1;
        uniqueTerms.push(rawTerms[i]);
      }
    }

    // Handle filter-only query like "site:cs.redwood.edu"
    if (uniqueTerms.length === 0 && (filterSlice || filterDomain) && !cleanQuery.replace(/\s+/g, "")) {
      var filteredDocs = [];
      for (i = 0; i < _pagesList.length; i++) {
        var fdDoc = _pagesList[i];
        if (!docMatchesFilters(fdDoc, filterSlice, filterDomain)) continue;
        var fdPr = computePrMultiplier(fdDoc);
        filteredDocs.push({
          doc: fdDoc,
          finalScore: Math.round(fdPr * 1000) / 100,
          irScore: 0,
          titleScore: 0,
          anchorScore: 0,
          bodyScore: 0,
          prScore: Math.round(fdPr * 100) / 100,
          matchedTerms: [],
          matchedAnchors: [],
          snippetHtml: escapeHtml(fdDoc.excerpt || "")
        });
      }
      filteredDocs.sort(function (a, b) {
        if ((b.doc.pagerank || 0) !== (a.doc.pagerank || 0)) return (b.doc.pagerank || 0) - (a.doc.pagerank || 0);
        return a.doc.id < b.doc.id ? -1 : (a.doc.id > b.doc.id ? 1 : 0);
      });
      var fdSlice = hasLimit ? filteredDocs.slice(offset, offset + limit) : filteredDocs.slice(offset);
      return {
        query: query || "",
        terms: [],
        totalResults: filteredDocs.length,
        elapsedSec: "0.01",
        results: fdSlice
      };
    }

    // Handle stopword-only queries gracefully
    if (uniqueTerms.length === 0) {
      var rawFallbackWords = tokenizeRaw(cleanQuery);
      if (rawFallbackWords.length === 0) {
        return {
          query: query || "",
          terms: [],
          totalResults: 0,
          elapsedSec: "0.01",
          results: []
        };
      }
      var fbRes = runRawStopwordFallback(rawFallbackWords, filterSlice, filterDomain);
      var fbTotal = fbRes.scored.length;
      var fbSlice = hasLimit ? fbRes.scored.slice(offset, offset + limit) : fbRes.scored.slice(offset);
      var tFb = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
      return {
        query: query || "",
        terms: fbRes.terms,
        totalResults: fbTotal,
        elapsedSec: Math.max(0.01, (tFb - t0) / 1000).toFixed(2),
        results: fbSlice
      };
    }

    var N = (_index && _index.doc_count) ? _index.doc_count : (_pagesList.length || 500);
    var termsMap = (_index && _index.terms) ? _index.terms : {};
    var candMap = {};
    var candList = [];

    for (i = 0; i < uniqueTerms.length; i++) {
      var term = uniqueTerms[i];
      var postings = Object.prototype.hasOwnProperty.call(termsMap, term) ? termsMap[term] : null;
      if (!postings || postings.length === 0) continue;

      var df = postings.length;
      var idf = Math.log(1.0 + (N - df + 0.5) / (df + 0.5));

      for (j = 0; j < postings.length; j++) {
        var post = postings[j];
        var docId = post[0];
        var doc = _pagesMap[docId];
        if (!doc || !docMatchesFilters(doc, filterSlice, filterDomain)) continue;

        var tfT = post[1] || 0;
        var tfB = post[2] || 0;
        var tfA = post[3] || 0;
        var preWeight = post[4] || 0;

        var wT = tfT > 0 ? idf * (5.5 * tfT / (tfT + 0.8)) : 0;
        var wA = tfA > 0 ? idf * (5.0 * tfA / (tfA + 1.8)) : 0;
        var wB = tfB > 0 ? Math.max(0, preWeight - wT - wA) : 0;
        if (tfB > 0 && wB === 0 && preWeight > 0) {
          wB = idf * (2.6 * tfB / (tfB + 1.5));
        }

        var cand;
        if (!Object.prototype.hasOwnProperty.call(candMap, docId)) {
          cand = {
            doc: doc,
            titleScoreRaw: 0,
            anchorScoreRaw: 0,
            bodyScoreRaw: 0,
            matchedTerms: []
          };
          candMap[docId] = cand;
          candList.push(cand);
        } else {
          cand = candMap[docId];
        }
        cand.titleScoreRaw += wT;
        cand.anchorScoreRaw += wA;
        cand.bodyScoreRaw += wB;
        cand.matchedTerms.push(term);
      }
    }

    var M = uniqueTerms.length;
    var scoredResults = [];

    for (i = 0; i < candList.length; i++) {
      var c = candList[i];
      var cDoc = c.doc;
      var matchedCount = c.matchedTerms.length;
      var coordRatio = matchedCount / M;
      var coordFactor = 1.0;

      if (M > 1) {
        if (matchedCount === M) {
          coordFactor = 1.0 + 0.15 * Math.min(M - 1, 4);
        } else {
          coordFactor = Math.pow(coordRatio, 2.5) * 0.35;
        }
      }

      var titlePhraseBonus = 0;
      var anchorPhraseBonus = 0;
      var bodyPhraseBonus = 0;

      // Evaluate inbound anchors matching query terms for both ranking & matchedAnchors
      var inboundEdges = Object.prototype.hasOwnProperty.call(_inboundByDoc, cDoc.id) ? _inboundByDoc[cDoc.id] : [];
      var matchedAnchors = [];
      var phraseAnchorHits = 0;
      var bestSingleAnchorOverlap = 0;

      if (inboundEdges.length > 0 && c.anchorScoreRaw > 0) {
        for (j = 0; j < inboundEdges.length; j++) {
          var edge = inboundEdges[j];
          var aToks = tokenize(edge.anchor_text);
          if (aToks.length === 0) continue;

          var aDistinct = {};
          var overlap = 0;
          for (var k = 0; k < aToks.length; k++) {
            var atk = aToks[k];
            if (Object.prototype.hasOwnProperty.call(termSet, atk) && !Object.prototype.hasOwnProperty.call(aDistinct, atk)) {
              aDistinct[atk] = 1;
              overlap += 1;
            }
          }
          if (overlap > 0) {
            var isExactAncPhrase = (rawTerms.length >= 2) ? hasPhraseInTokens(aToks, rawTerms) : false;
            if (isExactAncPhrase) {
              phraseAnchorHits += 1;
            }
            if (overlap > bestSingleAnchorOverlap) {
              bestSingleAnchorOverlap = overlap;
            }
            matchedAnchors.push({
              source_id: edge.source_id,
              source_title: edge.source_title,
              source_url: edge.source_url,
              anchor_text: edge.anchor_text,
              _overlap: overlap,
              _phrase: isExactAncPhrase ? 1 : 0,
              _srcPr: edge.source_pr || 0
            });
          }
        }

        if (matchedAnchors.length > 1) {
          matchedAnchors.sort(function (a, b) {
            if (b._phrase !== a._phrase) return b._phrase - a._phrase;
            if (b._overlap !== a._overlap) return b._overlap - a._overlap;
            if (b._srcPr !== a._srcPr) return b._srcPr - a._srcPr;
            return a.source_id < b.source_id ? -1 : (a.source_id > b.source_id ? 1 : 0);
          });
        }
      }

      if (rawTerms.length >= 2) {
        if (c.titleScoreRaw > 0) {
          var titleToks = tokenize(cDoc.title);
          if (hasPhraseInTokens(titleToks, rawTerms)) {
            titlePhraseBonus += 8.0 * (rawTerms.length - 1);
          } else {
            titlePhraseBonus += 2.2 * countAdjacentPairsInTokens(titleToks, rawTerms);
          }
        }

        if (phraseAnchorHits > 0) {
          anchorPhraseBonus += 9.0 * (rawTerms.length - 1) * (1.0 + 0.35 * Math.min(phraseAnchorHits - 1, 8));
        } else if (bestSingleAnchorOverlap >= 2) {
          anchorPhraseBonus += 2.5 * bestSingleAnchorOverlap;
        }

        if (c.bodyScoreRaw > 0) {
          var bodyToks = tokenize(cDoc.body_text);
          if (hasPhraseInTokens(bodyToks, rawTerms)) {
            bodyPhraseBonus += 4.5 * (rawTerms.length - 1);
          } else {
            bodyPhraseBonus += 1.2 * countAdjacentPairsInTokens(bodyToks, rawTerms);
          }
        }
      }

      var titleScore = (c.titleScoreRaw + titlePhraseBonus) * coordFactor;
      var anchorScore = (c.anchorScoreRaw + anchorPhraseBonus) * coordFactor;
      var bodyScore = (c.bodyScoreRaw + bodyPhraseBonus) * coordFactor;
      var irScore = titleScore + anchorScore + bodyScore;
      var prScore = computePrMultiplier(cDoc);
      var finalScore = irScore * prScore;

      // Strip internal sorting fields from matchedAnchors
      var cleanAnchors = [];
      var ancCap = Math.min(matchedAnchors.length, 10);
      for (j = 0; j < ancCap; j++) {
        var ma = matchedAnchors[j];
        cleanAnchors.push({
          source_id: ma.source_id,
          source_title: ma.source_title,
          source_url: ma.source_url,
          anchor_text: ma.anchor_text
        });
      }

      scoredResults.push({
        doc: cDoc,
        finalScore: finalScore,
        irScore: irScore,
        titleScore: titleScore,
        anchorScore: anchorScore,
        bodyScore: bodyScore,
        prScore: prScore,
        matchedTerms: c.matchedTerms,
        matchedAnchors: cleanAnchors,
        snippetHtml: ""
      });
    }

    scoredResults.sort(function (a, b) {
      if (b.finalScore !== a.finalScore) return b.finalScore - a.finalScore;
      if ((b.doc.pagerank || 0) !== (a.doc.pagerank || 0)) return (b.doc.pagerank || 0) - (a.doc.pagerank || 0);
      return a.doc.id < b.doc.id ? -1 : (a.doc.id > b.doc.id ? 1 : 0);
    });

    var totalResults = scoredResults.length;
    var pageSlice = hasLimit ? scoredResults.slice(offset, offset + limit) : scoredResults.slice(offset);

    for (i = 0; i < pageSlice.length; i++) {
      var r = pageSlice[i];
      r.snippetHtml = buildSnippetHtml(
        r.doc,
        termSet,
        r.matchedAnchors,
        r.titleScore,
        r.anchorScore,
        r.bodyScore,
        false
      );
      r.finalScore = Math.round(r.finalScore * 100) / 100;
      r.irScore = Math.round(r.irScore * 100) / 100;
      r.titleScore = Math.round(r.titleScore * 100) / 100;
      r.anchorScore = Math.round(r.anchorScore * 100) / 100;
      r.bodyScore = Math.round(r.bodyScore * 100) / 100;
      r.prScore = Math.round(r.prScore * 100) / 100;
    }

    var t1 = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
    var elapsed = Math.max(0.01, (t1 - t0) / 1000).toFixed(2);

    return {
      query: query || "",
      terms: uniqueTerms,
      totalResults: totalResults,
      elapsedSec: elapsed,
      results: pageSlice
    };
  }

  var Engine = {
    ready: ready,
    tokenize: tokenize,
    search: search,
    getPageById: getPageById,
    getPageByUrl: getPageByUrl,
    getSimilarPages: getSimilarPages,
    getStats: getStats,
    getGraph: getGraph,
    getPagesMap: getPagesMap
  };

  root.Google98Engine = Engine;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = Engine;
  }
})(typeof window !== "undefined" ? window : globalThis);
