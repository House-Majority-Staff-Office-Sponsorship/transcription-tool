# transcription-tool

## Overview

The Transcription Tool is a backend service that monitors the Hawaii House of Representatives YouTube channel, downloads newly published videos, transcribes their audio, classifies them by committee code, and stores organized transcripts for later use.

The system is designed to run continuously and automatically convert legislative proceedings into searchable text documents.

**Key features:**
- Automated YouTube polling
- Audio extraction via `yt-dlp`
- Local transcription using a Whisper model (GPU)
- Committee code based classification
- Persistent storage of transcripts and metadata
- Fault-tolerant processing loop

---

## System Architecture

The pipeline operates in a continuous loop:

1. Poll the House YouTube channel for newly completed videos  
2. Add new videos to a pending queue  
3. Download audio for each pending video  
4. Transcribe audio using a Whisper model  
5. Classify transcript by committee  
6. Store results in:
   - SQLite database (metadata)
   - Local file storage (JSON + TXT transcript files)  
7. Log results and errors  

---

## Requirements

### Software
- Docker

### Hardware
- NVIDIA GPU (required for normal operation)
- CUDA-compatible environment

### Network
- Outbound HTTPS access to:
  - YouTube Data API
  - YouTube media/CDN endpoints
---

## Setup

### 1. Clone repository
```
git clone https://github.com/House-Majority-Staff-Office-Sponsorship/transcription-tool.git
cd transcription-tool
```

### 2. Create `.env` file

Copy `.env.example` and fill in required values:

```
YOUTUBE_API_KEY=your_api_key_here
```
Optionally if diarization has been set up, create a hugging face account, and create a read token:
```
WHISPERX_HF_TOKEN=your_token_here
```

### 3. Get YouTube API Key

- In a Google Cloud Console project 
- Enable YouTube Data API v3 
- Create an API key and place it in the `.env` file  

---

## Running the Application (Recommended)

### Using Docker Compose

```
docker compose up -d --build
```

This will:
- build the Docker image
- start the container
- mount required storage directories
- load environment variables
- enable GPU access (if configured)
Note that the first time building the image may take several minutes however subsequent runs should be faster due to caching. 
---

### Stopping the application

```
docker compose down
```

---

### Viewing logs
Note that this can be done the application is running to view real time logs and terminal output. 
```
docker compose logs -f
```

---

## Alternative (Manual Docker Run)

For development/testing only on Linux/Unix:

```
docker build -t transcription-tool:dev .
docker run --rm --gpus all --env-file .env \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/state:/app/state" \
  transcription-tool:dev
```
On Windows:
```
docker build -t transcription-tool:dev .
docker run --rm --gpus all --env-file .env \
  -v "%cd%/data:/app/data" \
  -v "%cd%/state:/app/state" \
  transcription-tool:dev
```

---

## Directory Structure

### Persistent storage (mounted)

#### `/data`
- `db/transcription.db` → SQLite database  
- `logs/transcription_tool.log` → log file  
- `transcripts/<committee>/<transcript file>.txt` → transcript text files  
- `transcripts/<committee>/<transcript file>.json` → transcript json files  

#### `/state`
- `pending_videos.json`
- `processed_videos.json`
- `failed_downloads.json`
- `youtube_playlist_cache.json`
- `youtube_state.json`

### Temporary storage (not persisted)
- `/tempdata`
  - audio files and intermediate processing artifacts  
  - deleted after successful processing  

---

## Configuration

Environment variables:

| Variable | Description | Default |
|--------|------------|--------|
| `YOUTUBE_API_KEY` | YouTube Data API key | required |
| `CHANNEL_ID` | YouTube channel ID | Hawaii House |
| `POLL_INTERVAL_SECONDS` | Number of seconds each cycle takes | 600 |
| `MAX_VIDEOS` | Max videos per cycle | configurable |
| `CHUNK_SECONDS` | The size of each chunk when using faster-whisper | 600 |
| `OVERLAP_SECONDS` | The amount of overlap used between chunks for faster-whisper | 5 |
| `MODEL_SIZE` | The size of the faster-whisper model | small |
| `DEVICE` | The runtime device | cuda |
| `COMPUTE_TYPE` | Datatype used for faster-whisper | int8 |
| `GOOGLE_DRIVE_UPLOAD_ENABLED` | Used for internal testing | false |
| `TRANSCRIPTION_BACKEND` | Which model is used for transcription | faster-whisper or whisperx |
| `WHISPERX_MODEL_SIZE` | Size of the whisperx model | small |
| `WHISPERX_COMPUTE_TYPE` | Datatype used for whisperx | float16 |
| `WHISPERX_BATCH_SIZE` | Batch size used for whisperx | 16 |
| `WHISPERX_LANGUAGE` | The language the text is transcribed into for whisperx | en |
| `WHISPERX_ALIGN` | If whisperx is using alignment for its transcription, adds to the runtime | true |
| `WHISPERX_DIARIZE` | If whisperx is doing standard transcription or doing transcription + diarization. Note currently this is not implemented | false |
| `WHISPERX_HF_TOKEN`| A read only hugging face token required if `WHISPERX_DIARIZE = true` | optional


---

## Classification System

Videos are classified based on title:

- 3-letter committee codes (e.g., `JHA`, `FIN`)
- Joint hearings (`CODE-CODE`)
- Special cases:
  - `House Chamber` → `HC`
  - `Conference` → `CR`
- Anything else → `UNCLASSIFIED`

---

## Logging

Logs are written to:
- console (stdout)
- `/data/logs/transcription_tool.log`

Errors do not stop execution — the system continues processing in future cycles.

---

## Failure Handling

- Failed downloads are stored in `failed_downloads.json`
- Missing audio files are automatically reset to pending and retried
- The system is designed to recover from crashes without manual intervention

---

## Security Notes

- No inbound network access required
- No public API exposed
- Only outbound HTTPS requests
- Processes public YouTube data only
- API keys are passed via environment variables
---

## References and Acknowledgements

This project builds on several open-source tools, libraries, and APIs:

### Transcription Models
- **Whisper (OpenAI)** — https://github.com/openai/whisper  
- **faster-whisper** — https://github.com/guillaumekln/faster-whisper  
- **WhisperX** — https://github.com/m-bain/whisperx  
- **Hugging Face Hub** — https://huggingface.co/  

### Audio / Video Processing
- **yt-dlp** — https://github.com/yt-dlp/yt-dlp  
- **FFmpeg** — https://ffmpeg.org/  

### Machine Learning Runtime
- **CTranslate2** — https://github.com/OpenNMT/CTranslate2  
- **NVIDIA CUDA / cuDNN** — https://developer.nvidia.com/cuda-zone  

### APIs and Data Sources
- **YouTube Data API v3** — https://developers.google.com/youtube/v3  

### Python Libraries
- **google-api-python-client** — https://github.com/googleapis/google-api-python-client  
- **SQLAlchemy** — https://www.sqlalchemy.org/  
- **python-dotenv** — https://github.com/theskumar/python-dotenv  

### Containerization
- **Docker** — https://www.docker.com/  
- **Docker Compose** — https://docs.docker.com/compose/  

---

All transcription models are executed locally. No external transcription APIs are used. All processed data originates from publicly available YouTube content.

## Acknowledgements
We acknowledge and thank the maintainers and contributors of the above open-source projects for providing the tools that make this system possible.