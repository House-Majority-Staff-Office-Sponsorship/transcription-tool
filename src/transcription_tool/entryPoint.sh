#!/usr/bin/env bash
set -e

# Reconstruct Google OAuth client secret JSON from individual env vars
if [ -n "$GOOGLE_CLIENT_ID" ]; then
    cat > /app/client_secret.json <<EOJSON
{"installed":{"client_id":"${GOOGLE_CLIENT_ID}","project_id":"${GOOGLE_PROJECT_ID}","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_secret":"${GOOGLE_CLIENT_SECRET}","redirect_uris":["http://localhost"]}}
EOJSON
    export GOOGLE_DRIVE_OAUTH_CLIENT_JSON=/app/client_secret.json
fi

# Reconstruct Google OAuth token JSON from individual env vars
if [ -n "$GOOGLE_OAUTH_REFRESH_TOKEN" ]; then
    cat > /app/google-oauth-token.json <<EOJSON
{"token":"${GOOGLE_OAUTH_ACCESS_TOKEN}","refresh_token":"${GOOGLE_OAUTH_REFRESH_TOKEN}","token_uri":"https://oauth2.googleapis.com/token","client_id":"${GOOGLE_CLIENT_ID}","client_secret":"${GOOGLE_CLIENT_SECRET}","scopes":["https://www.googleapis.com/auth/drive.file"],"universe_domain":"googleapis.com","account":"","expiry":"2026-04-02T19:43:01.088176Z"}
EOJSON
    export GOOGLE_DRIVE_OAUTH_TOKEN_JSON=/app/google-oauth-token.json
fi

# Reconstruct service account JSON from individual env vars
if [ -n "$GOOGLE_SA_PRIVATE_KEY" ]; then
    cat > /app/service-account.json <<EOJSON
{"type":"service_account","project_id":"${GOOGLE_PROJECT_ID}","private_key_id":"${GOOGLE_SA_PRIVATE_KEY_ID}","private_key":"${GOOGLE_SA_PRIVATE_KEY}","client_email":"${GOOGLE_SA_CLIENT_EMAIL}","client_id":"${GOOGLE_SA_CLIENT_ID}","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":"${GOOGLE_SA_CERT_URL}","universe_domain":"googleapis.com"}
EOJSON
    export GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON=/app/service-account.json
fi

LD_EXTRA="$(python3 -c "
try:
    import os, nvidia.cublas.lib, nvidia.cudnn.lib
    print(os.path.dirname(nvidia.cublas.lib.__file__) + ':' + os.path.dirname(nvidia.cudnn.lib.__file__))
except Exception:
    print('')
" 2>/dev/null)"
if [ -n "$LD_EXTRA" ]; then
    export LD_LIBRARY_PATH="${LD_EXTRA}:${LD_LIBRARY_PATH}"
fi

# Start the transcription worker in the background
python3 -m transcription_tool &
WORKER_PID=$!

# Start the web dashboard in the foreground
exec uvicorn web.app:app --host 0.0.0.0 --port 8000
