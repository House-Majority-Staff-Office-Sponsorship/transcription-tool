#!/usr/bin/env bash
set -e

# Write Google credential JSON files from environment variables (for Coolify)
if [ -n "$GOOGLE_DRIVE_OAUTH_CLIENT_CONTENT" ]; then
    echo "$GOOGLE_DRIVE_OAUTH_CLIENT_CONTENT" > /app/client_secret.json
    export GOOGLE_DRIVE_OAUTH_CLIENT_JSON=/app/client_secret.json
fi

if [ -n "$GOOGLE_DRIVE_OAUTH_TOKEN_CONTENT" ]; then
    echo "$GOOGLE_DRIVE_OAUTH_TOKEN_CONTENT" > /app/google-oauth-token.json
    export GOOGLE_DRIVE_OAUTH_TOKEN_JSON=/app/google-oauth-token.json
fi

if [ -n "$GOOGLE_DRIVE_SERVICE_ACCOUNT_CONTENT" ]; then
    echo "$GOOGLE_DRIVE_SERVICE_ACCOUNT_CONTENT" > /app/service-account.json
    export GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON=/app/service-account.json
fi

export LD_LIBRARY_PATH="$(python3 -c "import os; import nvidia.cublas.lib; import nvidia.cudnn.lib; print(os.path.dirname(nvidia.cublas.lib.__file__) + ':' + os.path.dirname(nvidia.cudnn.lib.__file__))"):${LD_LIBRARY_PATH}"

# Start the transcription worker in the background
python3 -m transcription_tool &
WORKER_PID=$!

# Start the web dashboard in the foreground
exec uvicorn web.app:app --host 0.0.0.0 --port 8000
