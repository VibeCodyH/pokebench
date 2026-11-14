(function () {
  "use strict";

  var params = new URLSearchParams(window.location.search);
  var initialId = params.get("id") || "";
  var initialUrl = params.get("url") || "";
  var currentQuery = params.get("q") || "";

  var netscapeWindow = document.getElementById("netscapeWindow");
  var windowTitle = document.getElementById("windowTitle");
  var queryContextNote = document.getElementById("queryContextNote");
  var btnMinimize = document.getElementById("btnMinimize");
  var btnMaximize = document.getElementById("btnMaximize");
  var btnClose = document.getElementById("btnClose");

  var btnBack = document.getElementById("btnBack");
  var btnForward = document.getElementById("btnForward");
  var btnReload = document.getElementById("btnReload");
  var btnHome = document.getElementById("btnHome");
  var btnSearch = document.getElementById("btnSearch");
  var btnDirectory = document.getElementById("btnDirectory");
  var btnCache = document.getElementById("btnCache");

  var locationForm = document.getElementById("locationForm");
  var locationInput = document.getElementById("locationInput");
  var browserFrame = document.getElementById("browserFrame");
  var statusText = document.getElementById("statusText");
  var securityText = document.getElementById("securityText");

  var menuFile = document.getElementById("menuFile");
  var menuEdit = document.getElementById("menuEdit");
  var menuView = document.getElementById("menuView");
  var menuGo = document.getElementById("menuGo");
  var menuComm = document.getElementById("menuComm");
  var menuHelp = document.getElementById("menuHelp");

  var auxPanelRow = document.getElementById("auxPanelRow");
  var auxPanelTitle = document.getElementById("auxPanelTitle");
  var auxPanelBody = document.getElementById("auxPanelBody");
  var auxCloseBtn = document.getElementById("auxCloseBtn");

  var historyStack = [];
  var historyIndex = -1;
  var currentPage = null;
  var currentSourceHtml = "";
  var loadSequence = 0;
  var isMinimized = false;
  var isWindowedWidth = false;

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function setStatus(msg) {
    if (statusText) {
      statusText.textContent = msg;
    }
  }

  function updateFrameHeight() {
    if (!browserFrame) return;
    if (isMinimized) {
      browserFrame.height = "220";
      return;
    }
    var winH = window.innerHeight || 720;
    var targetH = winH - 210;
    if (targetH < 360) targetH = 360;
    browserFrame.height = String(targetH);
  }

  function updateNavButtons() {
    var canBack = historyIndex > 0;
    var canForward = historyIndex >= 0 && historyIndex < historyStack.length - 1;

    if (btnBack) {
      btnBack.disabled = !canBack;
      btnBack.className = canBack ? "ns-nav-btn" : "ns-nav-btn-disabled";
    }
    if (btnForward) {
      btnForward.disabled = !canForward;
      btnForward.className = canForward ? "ns-nav-btn" : "ns-nav-btn-disabled";
    }
  }

  function syncAddressBar(page) {
    if (!page) return;
    if (locationInput) {
      locationInput.value = page.url || "";
    }
    var titleLabel = "Netscape - [" + (page.title || page.url || "Untitled") + "]";
    if (windowTitle) {
      windowTitle.textContent = titleLabel;
    }
    document.title = titleLabel;

    try {
      var nextParams = new URLSearchParams();
      nextParams.set("id", page.id);
      if (currentQuery) {
        nextParams.set("q", currentQuery);
      }
      window.history.replaceState(null, "", "viewer.html?" + nextParams.toString());
    } catch (e) {}
  }

  function normalizeLookupUrl(raw) {
    if (!raw) return "";
    var s = String(raw).replace(/^\s+|\s+$/g, "");
    if (!s) return "";
    if (!/^https?:\/\//i.test(s)) {
      s = "http://" + s;
    }
    return s;
  }

  function splitHash(urlStr) {
    var idx = urlStr.indexOf("#");
    if (idx === -1) {
      return { clean: urlStr, hash: "" };
    }
    return {
      clean: urlStr.substring(0, idx),
      hash: urlStr.substring(idx + 1)
    };
  }

  function resolveCorpusPage(rawInputUrl) {
    if (!window.Google98Engine) return null;
    var normalized = normalizeLookupUrl(rawInputUrl);
    if (!normalized) return null;
    var parts = splitHash(normalized);
    var clean = parts.clean;

    var page = window.Google98Engine.getPageByUrl(clean);
    if (page) return { page: page, hash: parts.hash };

    if (clean.charAt(clean.length - 1) === "/") {
      page = window.Google98Engine.getPageByUrl(clean + "index.html");
      if (page) return { page: page, hash: parts.hash };
    } else if (!/\.html?$/i.test(clean)) {
      page = window.Google98Engine.getPageByUrl(clean + "/index.html");
      if (page) return { page: page, hash: parts.hash };
    }

    var map = window.Google98Engine.getPagesMap();
    if (map) {
      var targetCanonical = clean.toLowerCase().replace(/^https?:\/\//, "").replace(/\/index\.html$/, "").replace(/\/$/, "");
      for (var id in map) {
        if (Object.prototype.hasOwnProperty.call(map, id)) {
          var cand = map[id];
          if (!cand || !cand.url) continue;
          var candCanonical = cand.url.toLowerCase().replace(/^https?:\/\//, "").replace(/\/index\.html$/, "").replace(/\/$/, "");
          if (candCanonical === targetCanonical) {
            return { page: cand, hash: parts.hash };
          }
        }
      }
    }

    if (/^doc_\d+$/i.test(String(rawInputUrl).replace(/^\s+|\s+$/g, ""))) {
      var byId = window.Google98Engine.getPageById(String(rawInputUrl).replace(/^\s+|\s+$/g, ""));
      if (byId) return { page: byId, hash: "" };
    }

    return null;
  }

  function prepareFrameHtml(rawHtml, page) {
    var baseHref = "";
    try {
      baseHref = new URL(page.path, window.location.href).href;
    } catch (e) {
      baseHref = page.path;
    }
    var baseTag = '<base href="' + escapeHtml(baseHref) + '">';

    if (/<head[^>]*>/i.test(rawHtml)) {
      return rawHtml.replace(/(<head[^>]*>)/i, "$1\n" + baseTag);
    }
    if (/<html[^>]*>/i.test(rawHtml)) {
      return rawHtml.replace(/(<html[^>]*>)/i, "$1\n<head>" + baseTag + "</head>");
    }
    return "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.0 Transitional//EN\"><html><head>" + baseTag + "<title>" + escapeHtml(page.title || page.url) + "</title></head><body>" + rawHtml + "</body></html>";
  }

  function buildFallbackHtml(page) {
    var graph = window.Google98Engine && typeof window.Google98Engine.getGraph === "function" ? window.Google98Engine.getGraph() : null;
    var outLinks = [];
    if (graph && graph.edges) {
      for (var i = 0; i < graph.edges.length; i++) {
        var edge = graph.edges[i];
        if (edge[0] === page.id) {
          var targetPg = window.Google98Engine.getPageById(edge[1]);
          if (targetPg) {
            outLinks.push({ url: targetPg.url, anchor: edge[2] || targetPg.title });
          }
        }
      }
    }

    var baseHref = window.location.href;
    var html = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN"><html><head>';
    html += '<base href="' + escapeHtml(baseHref) + '">';
    html += "<title>" + escapeHtml(page.title || page.url) + "</title></head>";
    html += '<body bgcolor="#ffffff" text="#000000" link="#0000cc" vlink="#551a8b">';
    html += '<table border="0" cellpadding="10" cellspacing="0" width="100%"><tr><td>';
    html += '<font face="Times New Roman, Times, serif" size="+2"><b>' + escapeHtml(page.title || page.url) + "</b></font><br>";
    html += '<font face="Arial, Helvetica, sans-serif" size="-1" color="#666666">';
    html += "URL: " + escapeHtml(page.url) + " | Author: " + escapeHtml(page.author || "Unknown") + " | Updated: " + escapeHtml(page.last_modified || "Sep 1998");
    html += "</font><hr>";
    html += '<font face="Times New Roman, Times, serif"><p>' + escapeHtml(page.body_text || page.excerpt || "") + "</p></font>";
    if (outLinks.length > 0) {
      html += "<hr><b>Links from this page:</b><ul>";
      for (var j = 0; j < outLinks.length; j++) {
        html += '<li><a href="' + escapeHtml(outLinks[j].url) + '">' + escapeHtml(outLinks[j].anchor) + "</a></li>";
      }
      html += "</ul>";
    }
    html += "</td></tr></table></body></html>";
    return html;
  }

  function buildNotFoundHtml(missingUrl) {
    var html = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN"><html><head><title>404 Not Found</title></head>';
    html += '<body bgcolor="#ffffff" text="#000000" link="#0000cc">';
    html += '<table border="1" cellpadding="12" cellspacing="0" width="90%" align="center" bgcolor="#eeeeee" style="margin-top:24px;">';
    html += '<tr><td>';
    html += '<font face="Arial, Helvetica, sans-serif" size="+1" color="#990000"><b>Netscape Error: Host or Page Not Found</b></font><hr>';
    html += '<font face="Arial, Helvetica, sans-serif" size="-1">';
    html += "<p>The requested URL <code>" + escapeHtml(missingUrl) + "</code> is not in the 500-page September 1998 Web archive.</p>";
    html += '<p>Try navigating to <a href="http://dir.webguide98.org/index.html">WebGuide \'98 Directory</a> or <a href="http://www.cs.redwood.edu/index.html">Redwood CS Department</a>, or return to <a href="#search-home">Google! Search</a>.</p>';
    html += "</font></td></tr></table></body></html>";
    return html;
  }

  function scrollToFragment(iframeDoc, frag) {
    if (!iframeDoc || !frag) return;
    var el = iframeDoc.getElementById(frag);
    if (!el) {
      var named = iframeDoc.getElementsByName(frag);
      if (named && named.length > 0) {
        el = named[0];
      }
    }
    if (el && el.scrollIntoView) {
      el.scrollIntoView();
    }
  }

  function handleAnchorClick(anchorEl, evt) {
    if (!anchorEl) return;
    if (evt && evt._nsHandled) return;
    var rawHref = anchorEl.getAttribute("href");
    if (!rawHref) return;

    if (evt) {
      evt._nsHandled = true;
      if (evt.preventDefault) evt.preventDefault();
      evt.returnValue = false;
    }

    if (rawHref === "#search-home") {
      window.location.href = currentQuery ? ("search.html?q=" + encodeURIComponent(currentQuery)) : "index.html";
      return;
    }

    if (rawHref.charAt(0) === "#") {
      var frag = rawHref.substring(1);
      try {
        scrollToFragment(browserFrame.contentDocument, frag);
        setStatus("Jumped to #" + frag);
      } catch (e) {}
      return;
    }

    if (/^mailto:/i.test(rawHref) || /^javascript:/i.test(rawHref)) {
      setStatus("Simulated 1998 link (" + rawHref + ")");
      return;
    }

    var base = (currentPage && currentPage.url) ? currentPage.url : "http://dir.webguide98.org/index.html";
    var resolved = rawHref;
    try {
      resolved = new URL(rawHref, base).href;
    } catch (e) {}

    var match = resolveCorpusPage(resolved);
    if (match && match.page) {
      openPage(match.page, true, match.hash);
    } else {
      currentPage = {
        id: "",
        url: resolved,
        title: "404 Not Found",
        size_kb: 1
      };
      if (locationInput) locationInput.value = resolved;
      if (windowTitle) windowTitle.textContent = "Netscape - [404 Not Found]";
      document.title = "Netscape - [404 Not Found]";
      setStatus("Document: Not found in 1998 archive (" + resolved + ")");
      currentSourceHtml = buildNotFoundHtml(resolved);
      browserFrame.srcdoc = currentSourceHtml;
    }
  }

  function attachFrameInterceptors(hashToScroll) {
    var iframeDoc = null;
    try {
      iframeDoc = browserFrame.contentDocument || (browserFrame.contentWindow && browserFrame.contentWindow.document);
    } catch (e) {}
    if (!iframeDoc) return;

    if (hashToScroll) {
      scrollToFragment(iframeDoc, hashToScroll);
    }

    var anchors = iframeDoc.getElementsByTagName("a");
    for (var i = 0; i < anchors.length; i++) {
      var a = anchors[i];
      if (!a.getAttribute("href")) continue;
      a.addEventListener("click", (function (el) {
        return function (ev) {
          handleAnchorClick(el, ev);
        };
      })(a), false);
    }

    iframeDoc.addEventListener("click", function (ev) {
      if (ev._nsHandled) return;
      var node = ev.target;
      while (node && node !== iframeDoc) {
        if (node.tagName && node.tagName.toUpperCase() === "A" && node.getAttribute("href")) {
          handleAnchorClick(node, ev);
          return;
        }
        node = node.parentNode;
      }
    }, true);

    iframeDoc.addEventListener("mouseover", function (ev) {
      var node = ev.target;
      while (node && node !== iframeDoc) {
        if (node.tagName && node.tagName.toUpperCase() === "A" && node.getAttribute("href")) {
          var raw = node.getAttribute("href");
          if (raw.charAt(0) === "#") {
            setStatus("Section: " + raw);
          } else {
            try {
              var full = new URL(raw, (currentPage && currentPage.url) || "http://dir.webguide98.org/index.html").href;
              setStatus(full);
            } catch (e) {
              setStatus(raw);
            }
          }
          return;
        }
        node = node.parentNode;
      }
    }, false);

    iframeDoc.addEventListener("mouseout", function (ev) {
      var node = ev.target;
      while (node && node !== iframeDoc) {
        if (node.tagName && node.tagName.toUpperCase() === "A") {
          var kb = (currentPage && currentPage.size_kb !== undefined) ? currentPage.size_kb : 2;
          setStatus("Document: Done (" + kb + " KB)");
          return;
        }
        node = node.parentNode;
      }
    }, false);

    var forms = iframeDoc.getElementsByTagName("form");
    for (var f = 0; f < forms.length; f++) {
      forms[f].addEventListener("submit", function (ev) {
        if (ev.preventDefault) ev.preventDefault();
        ev.returnValue = false;
        var qField = this.querySelector('input[name="q"]');
        if (qField && qField.value) {
          window.location.href = "search.html?q=" + encodeURIComponent(qField.value);
          return;
        }
        setStatus("CGI form submission simulated locally (1998 read-only archive).");
      }, false);
    }
  }

  function loadPageIntoFrame(page, hash) {
    if (!page || !browserFrame) return;
    currentPage = page;
    syncAddressBar(page);

    var seq = ++loadSequence;
    setStatus("Transferring data from " + page.url + "...");
    if (securityText) {
      securityText.textContent = "[SSL/Open] http://";
    }

    fetch(page.path).then(function (resp) {
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      return resp.text();
    }).then(function (rawHtml) {
      if (seq !== loadSequence) return;
      currentSourceHtml = rawHtml;
      var sizeKb = Math.max(1, Math.round(rawHtml.length / 1024));
      if (!page.size_kb) page.size_kb = sizeKb;
      var prepared = prepareFrameHtml(rawHtml, page);
      browserFrame.onload = function () {
        if (seq !== loadSequence) return;
        attachFrameInterceptors(hash);
        setStatus("Document: Done (" + (page.size_kb || sizeKb) + " KB)");
      };
      browserFrame.srcdoc = prepared;
    }).catch(function () {
      if (seq !== loadSequence) return;
      var fallback = buildFallbackHtml(page);
      currentSourceHtml = fallback;
      browserFrame.onload = function () {
        if (seq !== loadSequence) return;
        attachFrameInterceptors(hash);
        setStatus("Document: Done (" + (page.size_kb || 2) + " KB)");
      };
      browserFrame.srcdoc = fallback;
    });
  }

  function openPage(page, pushToHistory, hash) {
    if (!page) return;
    if (pushToHistory) {
      if (historyIndex < historyStack.length - 1) {
        historyStack = historyStack.slice(0, historyIndex + 1);
      }
      historyStack.push({
        docId: page.id,
        url: page.url,
        hash: hash || ""
      });
      historyIndex = historyStack.length - 1;
    }
    updateNavButtons();
    loadPageIntoFrame(page, hash || "");
  }

  function showAuxPanel(title, htmlBody) {
    if (!auxPanelRow || !auxPanelTitle || !auxPanelBody) return;
    auxPanelTitle.textContent = title;
    auxPanelBody.innerHTML = htmlBody;
    auxPanelRow.style.display = "";
  }

  function hideAuxPanel() {
    if (auxPanelRow) {
      auxPanelRow.style.display = "none";
    }
  }

  if (currentQuery && queryContextNote) {
    queryContextNote.innerHTML = 'Search query: <b>' + escapeHtml(currentQuery) + '</b> (<a href="search.html?q=' + encodeURIComponent(currentQuery) + '">Return to results</a>)';
  }

  if (btnBack) {
    btnBack.onclick = function () {
      if (historyIndex <= 0) return;
      historyIndex -= 1;
      var entry = historyStack[historyIndex];
      var pg = window.Google98Engine.getPageById(entry.docId) || window.Google98Engine.getPageByUrl(entry.url);
      if (pg) {
        openPage(pg, false, entry.hash);
      }
    };
  }

  if (btnForward) {
    btnForward.onclick = function () {
      if (historyIndex >= historyStack.length - 1) return;
      historyIndex += 1;
      var entry = historyStack[historyIndex];
      var pg = window.Google98Engine.getPageById(entry.docId) || window.Google98Engine.getPageByUrl(entry.url);
      if (pg) {
        openPage(pg, false, entry.hash);
      }
    };
  }

  if (btnReload) {
    btnReload.onclick = function () {
      if (currentPage && currentPage.path) {
        loadPageIntoFrame(currentPage, "");
      } else if (locationInput && locationInput.value) {
        var m = resolveCorpusPage(locationInput.value);
        if (m && m.page) openPage(m.page, false, m.hash);
      }
    };
  }

  if (btnHome) {
    btnHome.onclick = function () {
      window.location.href = "index.html";
    };
  }

  if (btnSearch) {
    btnSearch.onclick = function () {
      window.location.href = currentQuery ? ("search.html?q=" + encodeURIComponent(currentQuery)) : "search.html";
    };
  }

  if (btnClose) {
    btnClose.onclick = function () {
      window.location.href = currentQuery ? ("search.html?q=" + encodeURIComponent(currentQuery)) : "index.html";
    };
  }

  if (btnDirectory) {
    btnDirectory.onclick = function () {
      if (!window.Google98Engine) return;
      var dirPage = window.Google98Engine.getPageById("doc_0451");
      if (dirPage) {
        openPage(dirPage, true, "");
      }
    };
  }

  if (btnCache) {
    btnCache.onclick = function () {
      if (currentPage && currentPage.id) {
        var qSuffix = currentQuery ? ("&q=" + encodeURIComponent(currentQuery)) : "";
        window.location.href = "cached.html?id=" + encodeURIComponent(currentPage.id) + qSuffix;
      }
    };
  }

  if (btnMinimize) {
    btnMinimize.onclick = function () {
      isMinimized = !isMinimized;
      updateFrameHeight();
    };
  }

  if (btnMaximize) {
    btnMaximize.onclick = function () {
      isWindowedWidth = !isWindowedWidth;
      if (netscapeWindow) {
        netscapeWindow.width = isWindowedWidth ? "780" : "100%";
      }
    };
  }

  if (locationForm) {
    locationForm.onsubmit = function (ev) {
      if (ev && ev.preventDefault) ev.preventDefault();
      var raw = locationInput ? locationInput.value : "";
      var match = resolveCorpusPage(raw);
      if (match && match.page) {
        openPage(match.page, true, match.hash);
      } else {
        var missing = normalizeLookupUrl(raw) || raw;
        currentPage = { id: "", url: missing, title: "404 Not Found", size_kb: 1 };
        setStatus("Document: Not found in 1998 archive (" + missing + ")");
        currentSourceHtml = buildNotFoundHtml(missing);
        if (browserFrame) {
          browserFrame.onload = function () {
            attachFrameInterceptors("");
          };
          browserFrame.srcdoc = currentSourceHtml;
        }
      }
      return false;
    };
  }

  var bookmarkLinks = document.querySelectorAll("a.ns-bookmark[data-doc-id]");
  for (var b = 0; b < bookmarkLinks.length; b++) {
    bookmarkLinks[b].onclick = function (ev) {
      if (ev && ev.preventDefault) ev.preventDefault();
      var targetId = this.getAttribute("data-doc-id");
      if (targetId && window.Google98Engine) {
        var pg = window.Google98Engine.getPageById(targetId);
        if (pg) {
          openPage(pg, true, "");
        }
      }
      return false;
    };
  }

  if (auxCloseBtn) {
    auxCloseBtn.onclick = hideAuxPanel;
  }

  if (menuView) {
    menuView.onclick = function (ev) {
      if (ev && ev.preventDefault) ev.preventDefault();
      var src = currentSourceHtml || "(No source loaded yet)";
      showAuxPanel(
        "Document Source - " + (currentPage ? currentPage.url : ""),
        "<pre style=\"margin:0; white-space:pre-wrap;\">" + escapeHtml(src) + "</pre>"
      );
      return false;
    };
  }

  if (menuHelp) {
    menuHelp.onclick = function (ev) {
      if (ev && ev.preventDefault) ev.preventDefault();
      showAuxPanel(
        "About Netscape Communicator 4.06",
        "<font face=\"Arial, Helvetica, sans-serif\" size=\"-1\">" +
        "<b>Netscape Communicator 4.06 (Historical Frame Simulation)</b><br>" +
        "Browse all 500 pages of the September 1998 Web Corpus. Every hyperlink inside any page resolves locally against the 1998 index.<br>" +
        "Use <b>Back</b>, <b>Forward</b>, <b>Directory</b>, <b>Cache</b>, or type any corpus <code>http://...</code> URL in the Location bar." +
        "</font>"
      );
      return false;
    };
  }

  if (menuFile) {
    menuFile.onclick = function (ev) {
      if (ev && ev.preventDefault) ev.preventDefault();
      if (btnCache && currentPage && currentPage.id) {
        btnCache.click();
      }
      return false;
    };
  }

  if (menuGo) {
    menuGo.onclick = function (ev) {
      if (ev && ev.preventDefault) ev.preventDefault();
      if (historyIndex > 0 && btnBack) {
        btnBack.click();
      } else if (btnDirectory) {
        btnDirectory.click();
      }
      return false;
    };
  }

  if (menuEdit) {
    menuEdit.onclick = function (ev) {
      if (ev && ev.preventDefault) ev.preventDefault();
      if (locationInput) {
        locationInput.focus();
        locationInput.select();
      }
      return false;
    };
  }

  if (menuComm) {
    menuComm.onclick = function (ev) {
      if (ev && ev.preventDefault) ev.preventDefault();
      if (btnDirectory) btnDirectory.click();
      return false;
    };
  }

  updateFrameHeight();
  window.addEventListener("resize", updateFrameHeight);

  if (!window.Google98Engine || typeof window.Google98Engine.ready !== "function") {
    setStatus("Error: Google98Engine (js/engine.js) could not be loaded.");
    return;
  }

  setStatus("Initializing September 1998 Web index...");
  window.Google98Engine.ready().then(function () {
    var startPage = null;
    var startHash = "";

    if (initialId) {
      startPage = window.Google98Engine.getPageById(initialId);
    }
    if (!startPage && initialUrl) {
      var m = resolveCorpusPage(initialUrl);
      if (m) {
        startPage = m.page;
        startHash = m.hash;
      }
    }
    if (!startPage) {
      startPage = window.Google98Engine.getPageById("doc_0451") || window.Google98Engine.getPageById("doc_0001");
    }

    if (startPage) {
      openPage(startPage, true, startHash);
    } else {
      setStatus("No starting document found in 1998 index.");
      if (browserFrame) {
        browserFrame.srcdoc = buildNotFoundHtml(initialId || initialUrl || "unknown");
      }
    }
  }).catch(function (err) {
    setStatus("Engine load error: " + (err && err.message ? err.message : String(err)));
  });
})();
