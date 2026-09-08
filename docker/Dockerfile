# Build from the repo root:  docker build -f docker/Dockerfile -t pokebench-server .
# Run (Ollama on the same host, ROM + runs mounted):
#   docker run -d --name pokebench-server --network host --restart unless-stopped \
#     -v /path/to/roms:/app/roms -v /path/to/runs:/app/runs pokebench-server
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /app
COPY serve_live.py qwen_red.py milestones.py stream.html /app/
ENV OLLAMA_HOST=http://localhost:11434
EXPOSE 8765
CMD ["python", "serve_live.py", "--rom", "/app/roms/Pokemon Red.gb"]
