#!/usr/bin/env bash
# One foreground process: Ctrl-C / SIGTERM stops capture and finalizes the archive.
set -euo pipefail
exec node <<'NODE'
'use strict';
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { performance } = require('node:perf_hooks');
const { createInterface } = require('node:readline');

const fps = 30;
const streamURL = process.env.STREAM_URL || 'http://localhost:8765/stream';
const rtmpURL = process.env.RTMP_URL || '';
const rtmpURL2 = process.env.RTMP_URL2 || '';
const resolutions = { '1080p': [1920, 1080], '720p': [1280, 720] };
const res = process.env.RES || '1080p';
const archiveDir = path.resolve(process.env.ARCHIVE_DIR || '/recordings');
const chromiumBin = process.env.CHROMIUM_BIN || 'chromium';
let browser, encoder, probe, profile, archive, session;
let stopping = false, latestFrame, timer, sequence = 0, cdpBuffer = '';
const pending = new Map();
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const log = message => console.error(`[recorder] ${message}`);

// FFmpeg can include the destination in error messages. Never log the stream key.
const rtmpTargets = [rtmpURL, rtmpURL2].filter(Boolean);
function redact(line) {
  for (const url of rtmpTargets) {
    line = line.split(url).join('[RTMP_URL]');
    const key = url.split('/').pop()?.split('?')[0];
    if (key) line = line.split(key).join('[STREAM_KEY]');
  }
  return line;
}
function child(command, args, stdio) {
  const proc = spawn(command, args, { stdio, detached: true });
  proc.done = new Promise(resolve => {
    proc.once('error', error => { log(`${command}: ${redact(error.message)}`); resolve(1); });
    proc.once('exit', (code, signal) => resolve(code ?? (signal ? 1 : 0)));
  });
  if (proc.stderr) createInterface({ input: proc.stderr }).on('line', line => log(redact(line)));
  return proc;
}
function killGroup(proc, signal) {
  if (!proc?.pid) return;
  try { process.kill(-proc.pid, signal); } catch (error) {
    if (error.code !== 'ESRCH') log(`Could not stop child: ${error.code}`);
  }
}
async function shutdown(code, reason) {
  if (stopping) return;
  stopping = true;
  clearTimeout(timer);
  log(reason);
  // A wedged browser, encoder or network must not outlive Docker's stop grace.
  const hardStop = setTimeout(() => {
    for (const proc of [browser, encoder, probe]) killGroup(proc, 'SIGKILL');
    log('Stop timed out; last MP4 fragment may be incomplete.');
    process.exit(1);
  }, 30000);
  for (const { reject, timeout } of pending.values()) {
    clearTimeout(timeout);
    reject(new Error('Recorder stopping'));
  }
  pending.clear();
  killGroup(browser, 'SIGTERM');
  killGroup(probe, 'SIGTERM');
  // EOF lets FFmpeg drain video and stop the synthetic audio via -shortest.
  if (encoder?.stdin && !encoder.stdin.destroyed) encoder.stdin.end();
  if (encoder && await encoder.done !== 0) code = 1;
  if (browser) {
    const reap = setTimeout(() => killGroup(browser, 'SIGKILL'), 3000);
    await browser.done;
    clearTimeout(reap);
  }
  if (probe) await probe.done;
  if (profile) fs.rmSync(profile, { recursive: true, force: true });
  clearTimeout(hardStop);
  log(archive ? `Stopped (${code}); archive: ${archive}` : `Stopped (${code}).`);
  process.exit(code);
}
process.on('SIGINT', () => void shutdown(0, 'Stopping capture.'));
process.on('SIGTERM', () => void shutdown(0, 'Stopping capture.'));
process.on('uncaughtException', error => void shutdown(1, redact(error.message)));
process.on('unhandledRejection', error => void shutdown(1, redact(String(error))));

// CDP over Chromium's inherited pipes: no WebSocket library or exposed debug port.
function cdp(method, params = {}, sessionId = session) {
  if (stopping) return Promise.reject(new Error('Recorder stopping'));
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`Chromium timed out: ${method}`));
    }, 15000);
    pending.set(id, { resolve, reject, timeout });
    browser.stdio[3].write(JSON.stringify({ id, method, params, sessionId }) + '\0');
  });
}
function receiveCDP(chunk) {
  cdpBuffer += chunk;
  let end;
  while ((end = cdpBuffer.indexOf('\0')) !== -1) {
    const message = JSON.parse(cdpBuffer.slice(0, end));
    cdpBuffer = cdpBuffer.slice(end + 1);
    if (pending.has(message.id)) {
      const { resolve, reject, timeout } = pending.get(message.id);
      pending.delete(message.id);
      clearTimeout(timeout);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
    } else if (message.method === 'Page.screencastFrame' && message.sessionId === session) {
      latestFrame = Buffer.from(message.params.data, 'base64');
      // Acknowledge immediately; retain only the newest frame, never a frame backlog.
      void cdp('Page.screencastFrameAck', { sessionId: message.params.sessionId });
    } else if (message.method === 'Inspector.targetCrashed') {
      void shutdown(1, 'Chromium renderer crashed.');
    }
  }
}

async function main() {
  if (!resolutions[res]) throw new Error('RES must be 1080p or 720p.');
  if (!['http:', 'https:'].includes(new URL(streamURL).protocol)) {
    throw new Error('STREAM_URL must be an HTTP(S) URL.');
  }
  for (const url of rtmpTargets) {
    if (!['rtmp:', 'rtmps:'].includes(new URL(url).protocol) || /[\s|\\'\[\]]/.test(url)) {
      throw new Error('RTMP_URL / RTMP_URL2 must be RTMP(S) URLs without spaces or tee control characters.');
    }
  }
  const [width, height] = resolutions[res];
  const bitrate = res === '720p' ? '3000k' : '4500k';
  fs.mkdirSync(archiveDir, { recursive: true });
  process.chdir(archiveDir);

  log(`Checking h264_nvenc at ${width}x${height}.`);
  probe = child('ffmpeg', [
    '-hide_banner', '-loglevel', 'error', '-nostdin', '-f', 'lavfi',
    '-i', `color=size=${width}x${height}:rate=${fps}`, '-frames:v', '1',
    '-c:v', 'h264_nvenc', '-preset', 'p4', '-pix_fmt', 'yuv420p', '-f', 'null', '-'
  ], ['ignore', 'ignore', 'pipe']);
  const probeTimeout = setTimeout(() => void shutdown(1, 'NVENC check timed out.'), 15000);
  const probeCode = await probe.done;
  clearTimeout(probeTimeout);
  if (stopping) return;
  probe = null;
  if (probeCode !== 0) throw new Error('NVENC unavailable: check NVIDIA runtime, video/compute capabilities and host driver.');

  profile = fs.mkdtempSync(path.join(os.tmpdir(), 'pokebench-recorder-'));
  browser = child(chromiumBin, [
    '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
    '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--mute-audio',
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    '--disable-backgrounding-occluded-windows', '--remote-debugging-pipe',
    '--log-level=3', `--user-data-dir=${profile}`, `--window-size=${width},${height}`, 'about:blank'
  ], ['ignore', 'ignore', 'pipe', 'pipe', 'pipe']);
  browser.done.then(() => { if (!stopping) void shutdown(1, 'Chromium exited unexpectedly.'); });
  browser.stdio[3].on('error', error => { if (!stopping) void shutdown(1, error.message); });
  browser.stdio[4].setEncoding('utf8');
  browser.stdio[4].on('data', receiveCDP);
  browser.stdio[4].on('end', () => { if (!stopping) void shutdown(1, 'Chromium CDP pipe closed.'); });
  const { targetId } = await cdp('Target.createTarget', { url: 'about:blank' });
  ({ sessionId: session } = await cdp('Target.attachToTarget', { targetId, flatten: true }));
  await cdp('Page.enable');
  await cdp('Inspector.enable');
  // Modern headless Chrome still reserves window chrome. Resize the actual
  // window before emulation, or screencast JPEGs can clip the viewport bottom.
  const { windowId } = await cdp('Browser.getWindowForTarget', { targetId });
  const { result: chromeSize } = await cdp('Runtime.evaluate', {
    expression: '({width: outerWidth - innerWidth, height: outerHeight - innerHeight})', returnByValue: true
  });
  await cdp('Browser.setWindowBounds', { windowId, bounds: {
    width: width + chromeSize.value.width, height: height + chromeSize.value.height
  } });
  await cdp('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  const navigation = await cdp('Page.navigate', { url: streamURL });
  if (navigation.errorText) throw new Error(`Dashboard navigation failed: ${navigation.errorText}`);
  let ready = false;
  for (let tries = 0; tries < 100 && !stopping; tries++) {
    const { result } = await cdp('Runtime.evaluate', { expression: 'document.readyState' });
    if (result.value === 'complete') { ready = true; break; }
    await delay(100);
  }
  if (!ready) throw new Error('Dashboard did not finish loading.');
  // Refuse HTTP error pages, which Chromium otherwise considers successful loads.
  const { result: status } = await cdp('Runtime.evaluate', {
    expression: 'fetch(location.href, {cache: "no-store"}).then(r => r.ok)', awaitPromise: true
  });
  if (status.value !== true) throw new Error('Dashboard HTTP check failed.');
  // The dashboard's natural-width Game Boy image otherwise pushes reasoning
  // below a 16:9 viewport. Fit it in this tab only; leave stream.html untouched.
  await cdp('Runtime.evaluate', { expression: `(() => {
    const style = document.createElement('style');
    style.textContent = '#stage .screen-wrap{flex:1 1 0;min-height:0}' +
      '#stage .readout{flex-shrink:0}' +
      '#screen{height:100%;aspect-ratio:auto;object-fit:contain}';
    document.head.appendChild(style);
  })()` });
  await cdp('Page.startScreencast', { format: 'jpeg', quality: 85, maxWidth: width, maxHeight: height, everyNthFrame: 1 });
  // Seed static pages; CDP only emits frames when the compositor has an update.
  const first = await cdp('Page.captureScreenshot', { format: 'jpeg', quality: 85, captureBeyondViewport: false });
  latestFrame = Buffer.from(first.data, 'base64');

  const filename = `pokebench-${new Date().toISOString().replace(/[:.]/g, '-')}-${randomUUID()}.mp4`;
  archive = path.join(archiveDir, filename);
  // Reserve an append-only name before FFmpeg opens it through the tee muxer.
  fs.closeSync(fs.openSync(filename, 'wx'));
  let outputs = `[f=mp4:onfail=abort:movflags=+frag_keyframe+empty_moov+default_base_moof]${filename}`;
  // Use the FIFO muxer directly (one per RTMP target) to avoid tee's second-level option escaping.
  for (const url of rtmpTargets) {
    outputs += `|[f=fifo:onfail=ignore:fifo_format=flv:queue_size=120:drop_pkts_on_overflow=1:attempt_recovery=1:recover_any_error=1:recovery_wait_time=5:restart_with_keyframe=1:format_opts=rw_timeout=5000000]${url}`;
  }
  // Game audio: serve_live streams the emulator's PCM at /audio.pcm (parameters at /audio/info).
  // Older servers lack it; fall back to a silent track so the recording still runs.
  let audioInput = ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000'];
  let audioFilter = [];
  try {
    const reply = await fetch(new URL('/audio/info', streamURL));
    if (!reply.ok) throw new Error(`HTTP ${reply.status}`);
    const info = await reply.json();
    audioInput = ['-f', info.sample_format, '-ar', String(info.sample_rate), '-ac', String(info.channels),
      '-thread_queue_size', '1024', '-i', new URL('/audio.pcm', streamURL).href];
    // PyBoy's mix is quiet (peaks ~10/127) and rides a DC offset: strip the DC, lift it, soft-limit the peaks.
    // AUDIO_GAIN is the lift. 4 was loud enough on the stream to be a complaint (2026-09-16), so 2 is the default.
    const gain = Number(process.env.AUDIO_GAIN) > 0 ? Number(process.env.AUDIO_GAIN) : 2;
    audioFilter = ['-af', `highpass=f=20,volume=${gain},alimiter=limit=0.9:level=false`];
    log(`Game audio: ${info.sample_format} ${info.sample_rate} Hz from /audio.pcm.`);
  } catch (error) {
    log(`No game audio (${error.message}); encoding silence.`);
  }
  encoder = child('ffmpeg', [
    '-hide_banner', '-loglevel', 'warning', '-nostdin',
    '-thread_queue_size', '8', '-f', 'image2pipe', '-framerate', String(fps),
    '-probesize', '1000000', '-analyzeduration', '0', '-vcodec', 'mjpeg', '-i', 'pipe:0',
    ...audioInput,
    '-map', '0:v:0', '-map', '1:a:0',
    '-vf', `scale=${width}:${height}:flags=fast_bilinear,format=yuv420p`,
    '-c:v', 'h264_nvenc', '-preset', 'p4', '-tune', 'll', '-rc', 'cbr',
    '-b:v', bitrate, '-maxrate', bitrate, '-bufsize', res === '720p' ? '6000k' : '9000k',
    '-profile:v', 'high', '-g', '60', '-bf', '0', '-r', String(fps),
    '-flags', '+global_header', ...audioFilter, '-c:a', 'aac', '-b:a', '160k', '-ar', '48000',
    '-shortest', '-f', 'tee', outputs
  ], ['pipe', 'ignore', 'pipe']);
  encoder.stdin.on('error', error => { if (!stopping) void shutdown(1, `Encoder input failed: ${error.code}`); });
  encoder.done.then(() => { if (!stopping) void shutdown(1, 'FFmpeg exited unexpectedly; check disk space and NVENC.'); });
  log(`Recording ${width}x${height} at ${fps} fps -> ${archive}; RTMP targets: ${rtmpTargets.length}.`);

  // Fixed wall-clock pacing duplicates unchanged frames and drops superseded CDP
  // frames. Waiting on drain bounds memory; fail if encoding cannot keep up.
  const started = performance.now();
  let sent = 0;
  function writeFrame() {
    if (stopping) return;
    const behind = performance.now() - (started + sent * 1000 / fps);
    if (behind > 2000) { void shutdown(1, 'Encoder is over 2s behind real time; try RES=720p.'); return; }
    sent++;
    const accepted = encoder.stdin.write(latestFrame);
    const schedule = () => {
      if (!stopping) timer = setTimeout(writeFrame, Math.max(0, started + sent * 1000 / fps - performance.now()));
    };
    if (accepted) schedule();
    else {
      timer = setTimeout(() => void shutdown(1, 'Encoder stalled; stopping to preserve the archive.'), 15000);
      encoder.stdin.once('drain', () => { clearTimeout(timer); schedule(); });
    }
  }
  writeFrame();
  // A live but unresponsive renderer must not silently create an endless frozen VOD.
  const heartbeat = setInterval(() => {
    if (!stopping) void cdp('Runtime.evaluate', { expression: '1' });
  }, 10000);
  heartbeat.unref();
}
main().catch(error => { if (!stopping) void shutdown(1, redact(error.message)); });
NODE
