# Debian's FFmpeg is built with NVENC support. The NVIDIA container runtime
# supplies libcuda/libnvidia-encode from the host; no CUDA SDK or X server needed.
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash ca-certificates chromium ffmpeg fonts-dejavu-core fonts-noto-color-emoji nodejs tini \
    && ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_nvenc \
    && rm -rf /var/lib/apt/lists/*

ENV STREAM_URL=http://localhost:8765/stream \
    RES=1080p \
    ARCHIVE_DIR=/recordings \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,video,utility

WORKDIR /app
COPY record.sh /app/record.sh
RUN chmod 0755 /app/record.sh && mkdir /recordings
VOLUME ["/recordings"]
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/bin/tini", "--", "/app/record.sh"]
