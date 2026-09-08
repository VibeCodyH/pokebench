
## Stream view (stream.html at /stream, served by serve_live.py)
- serve_live.py wraps the pokemon-agent server: an idle ticker runs the emulator in real time between
  Qwen's turns and streams frames over the WebSocket at 30 fps; /stream is an OBS-friendly fixed 640x576
  view with the reasoning feed. Poll fallback (~8fps) kicks in if the WebSocket can't open.
- ★NOT A BUG: interior maps (Red's House etc.) legitimately render the small room in one corner with black
  around it (out-of-bounds). Frames are a real 160x144; the game just fills part of the GB screen indoors.
  Overworld/full maps fill the box. Do not "fix" the display for this — chased it for an hour, it was the room.
- ★Brave (and uBlock) block ws://localhost silently — the page hangs on "connecting…" with NO console error
  and falls back to poll. Turn OFF Brave Shields for localhost to get the live WebSocket feed.
- Point OBS at http://localhost:8765/stream ; keep /dashboard open separately only for START/PAUSE/STOP.
