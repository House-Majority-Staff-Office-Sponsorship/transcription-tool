FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app/src

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    ffmpeg \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir --upgrade pip && \
    python3 -m pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# Bake credential JSON files into the image
COPY client_secret.json /app/client_secret.json
COPY google-oauth-token.json /app/google-oauth-token.json
COPY service-account.json /app/service-account.json

ENV GOOGLE_DRIVE_OAUTH_CLIENT_JSON=/app/client_secret.json
ENV GOOGLE_DRIVE_OAUTH_TOKEN_JSON=/app/google-oauth-token.json
ENV GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON=/app/service-account.json

RUN chmod +x /app/src/transcription_tool/entryPoint.sh

EXPOSE 8000

CMD ["/app/src/transcription_tool/entryPoint.sh"]
