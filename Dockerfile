FROM node:20-bookworm-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build


FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/models/huggingface
ENV DISABLE_BROWSER_OAUTH=1
ENV YTDLP_USE_COOKIES=auto
ENV YTDLP_SLEEP_MIN=3
ENV YTDLP_SLEEP_MAX=6
ENV DENO_INSTALL=/root/.deno
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:/root/.deno/bin:${PATH}"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        python3 \
        python3-pip \
        python3-venv \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deno.land/install.sh | sh

COPY requirements.txt requirements-web.txt ./
RUN python3 -m venv "$VIRTUAL_ENV" \
    && python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements-web.txt

COPY backend ./backend
COPY blog ./blog
COPY transcription ./transcription
COPY config.yaml ./
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN python --version \
    && ffmpeg -version \
    && deno --version \
    && python -m backend.runtime_check

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
