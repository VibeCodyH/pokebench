# PokéBench headless recorder

Implements `BENCHMARK-SPEC.md` §4: one Chromium tab watches the live dashboard,
and FFmpeg encodes it with the RTX 3090's **h264_nvenc** encoder into a unique MP4
under `/recordings`. Set `RTMP_URL` to send the same encode to Twitch as well.
No display server, desktop session, OBS, or PC left running is needed.

## Capture and output

`record.sh` starts a persistent headless Chromium and uses
[CDP Page.startScreencast](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-startScreencast)
over inherited pipes. This preserves the dashboard's WebSocket connection and
avoids repeated browser launches, screenshot files, and an exposed debugging
port. Node.js supplies the small CDP client using only built-in modules.

CDP emits JPEGs when the page changes, rather than guaranteeing a frame rate.
The recorder acknowledges each frame immediately, keeps the newest one, and
pipes it to FFmpeg on a **30 fps wall clock**, repeating unchanged frames.
Memory is bounded; if the encoder cannot keep up, the recorder exits with an
error instead of silently producing a sped-up VOD. Chromium renders in software
to leave GPU memory for Ollama; only video encoding uses NVENC.

The recorder injects a small style into its own tab so the game image fits the
available height, preserving its aspect ratio and keeping the readout/reasoning
visible at both resolutions. `stream.html` on disk is unchanged.

[FFmpeg's tee and FIFO muxers](https://ffmpeg.org/ffmpeg-formats.html#tee)
share one H.264 encode between disk and Twitch. The archive is mandatory: a disk
error stops recording. Twitch gets a separate bounded queue, a five-second I/O
timeout, and reconnection attempts every five seconds; network failures may
drop live packets but do not block the archive. Check Twitch Inspector to
confirm the push is actually healthy. Silent stereo AAC is included for stream
compatibility; **browser/game audio is not captured**.

Archives use fragmented MP4 with two-second keyframes. Completed fragments
remain recoverable after an abrupt stop, although the last fragment may be lost.
Each start creates a new UTC timestamp + UUID filename; nothing is overwritten.
The normal stop path closes FFmpeg's input and waits for it to finish.

## Deploy through Unraid's GUI

These steps target **Unraid 10.0.0.77 with the RTX 3090**. The dashboard server
must already be running on that box and publishing port 8765.

1. Open `http://10.0.0.77` and check **Settings → NVIDIA Driver**. Install the
   NVIDIA Driver plugin through **Apps** if needed, following its reboot prompt.
   Confirm the 3090 appears and copy its `GPU-…` UUID. The host needs the NVIDIA
   Docker runtime as well as the driver; the existing Jellyfin/Ollama setup may
   already provide both. Do not bind this GPU exclusively to a VM.
2. Using the Unraid file manager or an SMB share in your PC's file manager, copy
   this **recorder folder's contents** into
   `/mnt/user/appdata/pokebench-recorder/`. That directory must contain
   `Dockerfile` and `record.sh` directly. Create
   `/mnt/user/data/pokebench-recordings/` for persistent video storage. Do not put
   recordings on Unraid's boot flash.
3. On the **Docker** page, open **Compose Manager / Compose Manager Plus** and
   choose **Add New Stack**, named `pokebench-recorder`. Open its **Edit Stack →
   Compose File** editor (button names vary by plugin version). Paste the YAML
   below and replace `GPU-REPLACE-WITH-3090-UUID` with the UUID from step 1.
4. Save, then choose **Build & Up** in Compose Manager Plus (or **Compose Up**
   in the older plugin, which builds a missing image). For later source changes,
   use **Update & Rebuild** in Plus. Its
   [build stack controls](https://github.com/mstrhakr/compose_plugin#features)
   detect the YAML's `build:` section. Open the container's **Logs**: expect the NVENC
   check followed by `Recording 1920x1080 at 30 fps`. An encoder listed in FFmpeg
   alone is insufficient; startup performs a real one-frame hardware encode.
5. Start with `RTMP_URL` empty. Record a short run, select **Stop** for the
   container, and open the resulting MP4 through your recordings share. Check
   the game and text move, resolution is correct, and duration matches the run.
   Then enable Twitch as described below.

```yaml
services:
  recorder:
    build:
      context: /mnt/user/appdata/pokebench-recorder
    image: pokebench-recorder:local
    container_name: pokebench-recorder
    runtime: nvidia
    network_mode: host
    environment:
      STREAM_URL: "http://localhost:8765/stream"
      RTMP_URL: "${RTMP_URL:-}"
      RES: "1080p"
      NVIDIA_VISIBLE_DEVICES: "GPU-REPLACE-WITH-3090-UUID"
      NVIDIA_DRIVER_CAPABILITIES: "compute,video,utility"
      TZ: "America/New_York"
    volumes:
      - /mnt/user/data/pokebench-recordings:/recordings
    shm_size: "256mb"
    stop_grace_period: 40s
    restart: "no"
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

`runtime: nvidia` plus `NVIDIA_VISIBLE_DEVICES` exposes the selected GPU and
injects its matching host driver libraries. The
[compute, video and utility capabilities](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html#driver-capabilities)
provide CUDA initialization, NVENC and diagnostics. No `privileged: true`,
manual `/dev/nvidia*` list, X socket, or display capability is required. The
Debian base installs NVENC-enabled FFmpeg and native Chromium packages; a full
CUDA development image is unnecessary. Rebuild to pick up package updates.

Host networking makes `localhost:8765` refer to the **Unraid host**, where the
server must listen or publish its container port. With bridge networking,
`localhost` means the recorder itself: use `http://10.0.0.77:8765/stream`, or a
server service name on a shared Docker network, instead. CDP uses pipes and
does not listen on a TCP port.

Chromium runs with `--no-sandbox` inside this container. Point it at the trusted
dashboard; the image has no browser login/profile persisted between runs.

## Settings and Twitch

| Variable | Default | Meaning |
| --- | --- | --- |
| `STREAM_URL` | `http://localhost:8765/stream` | Dashboard HTTP(S) URL reachable from the container. |
| `RTMP_URL` | empty | Empty means archive only; otherwise a complete Twitch ingest URL including stream key. |
| `RES` | `1080p` | `1080p` = 1920×1080 / 4.5 Mbps; `720p` = 1280×720 / 3 Mbps. Both are 30 fps. |
| `ARCHIVE_DIR` | `/recordings` | Writable output directory; normally leave this and change the volume's host path. |
| `CHROMIUM_BIN` | `chromium` | Browser executable override for a local installation. |

In Compose Manager's **Environment / .env** editor, set `RTMP_URL` to the full
URL using the ingest server and stream key from Twitch's creator dashboard:

```dotenv
RTMP_URL=rtmp://YOUR-INGEST-SERVER/app/YOUR-STREAM-KEY
```

Keep the key in that local environment file, not in this repo or shared YAML.
The recorder redacts the destination/key from child logs; Docker administrators
can still inspect container environment and process arguments. Save and recreate
the container with **Compose Up** after changing environment values. Setting a
real key starts broadcasting as soon as the recorder starts. For a private
connection test, append `?bandwidthtest=true` and check
[Twitch Inspector](https://dev.twitch.tv/docs/video-broadcast/#broadcast-urls-and-stream-keys);
remove that suffix when ready to go live.

## Start, stop, and resource budget

- **Start:** container **Start** / **Compose Up**, just before starting a model
  run. This recorder does not launch the model or infer when its turn budget ends.
- **Stop:** container **Stop**, or **Compose Down** for this separate stack.
  Wait for `Stopped (0)` in the logs. There is a 30-second cleanup deadline and
  a 40-second Docker grace period. The archive bind mount survives either action.
- **Automation:** start the container at run start and stop it at run end. It
  deliberately uses `restart: "no"` so a stopped run stays stopped and failures
  remain visible. Every restart opens a new archive; it never resumes a file.
- **Local foreground use:** with Chromium, Node.js and NVENC-enabled FFmpeg
  installed, run `ARCHIVE_DIR=/path/to/recordings bash recorder/record.sh`.
  Ctrl-C or SIGTERM uses the same cleanup path.
- **VRAM:** the §4 planning figure for **qwen3.8:27b@64k is 20.5/24 GB**, leaving
  about 3.5 GB. **1080p NVENC fits** that budget. If a **Jellyfin 4K transcode**
  runs concurrently, stop the recorder, set `RES: "720p"`, and recreate it before
  restarting the run (or reduce Ollama context). Actual headroom depends on the
  concurrent workload; the startup encode catches unavailable NVENC resources.
- **Storage:** budget roughly 2.1 GB/hour at 1080p or 1.4 GB/hour at 720p,
  including AAC. No automatic deletion or archive rotation is performed.

If startup reports `Cannot load libcuda`, `Cannot load libnvidia-encode`, an
unsupported driver/API, or no capable device, check the host driver, selected
GPU UUID, NVIDIA runtime and capabilities. There is no silent CPU fallback.
If the dashboard is unavailable at startup, recording exits with an error;
start its server and retry. Once loaded, the dashboard owns its data connection
and reconnection UI; this recorder checks renderer responsiveness, not model
progress or upstream feed freshness.
