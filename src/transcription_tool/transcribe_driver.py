from __future__ import annotations

import os
import json
import shutil
import subprocess
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Literal
from db.repository import ingest_transcript_json
from db.session import SessionLocal
from db.models import Video, Transcript, TranscriptSegment, TranscriptChunk
from sqlalchemy import select, func
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover
    WhisperModel = None  # type: ignore


DATA_DIR = Path("tempdata")
DATA_DIR.mkdir(parents=True, exist_ok=True)

PENDING_FILE = DATA_DIR / "pending_videos.json"
PROCESSED_FILE = DATA_DIR / "processed_videos.json"
FAILED_FILE = DATA_DIR / "failed_downloads.json"
AUDIO_DIR = DATA_DIR / "audio"
TESTING_DIR = DATA_DIR / "testing"

OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
AuthMode = Literal["oauth", "service_account"]


@dataclass
class ChunkResult:
    chunk_index: int
    chunk_path: str
    start_sec: float
    end_sec: float
    text: str
    segments: list[dict[str, Any]]




def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=True,
    )


def check_ffmpeg_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise RuntimeError(
                f"'{tool}' was not found on PATH. Install ffmpeg and make sure both "
                f"'ffmpeg' and 'ffprobe' are available."
            )


def get_audio_duration_seconds(audio_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = _run(cmd)
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(
            f"Could not read duration for audio file: {audio_path}\n"
            f"ffprobe output was: {result.stdout!r}"
        ) from exc

def remove_video_from_json(json_path: str | Path, video_id: str) -> bool:
    json_path = Path(json_path)

    if not json_path.exists():
        raise FileNotFoundError(f"JSON file not found: {json_path}")

    # Load existing data
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Expected JSON file to contain a list")

    original_length = len(data)

    # Filter out the video
    data = [item for item in data if item.get("video_id") != video_id]

    removed = len(data) < original_length

    # Safe write (write to temp file first)
    tmp_path = json_path.with_suffix(".tmp")

    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    tmp_path.replace(json_path)

    return removed


def make_audio_chunks(
    audio_path: Path,
    output_dir: Path,
    chunk_seconds: int = 600,
    overlap_seconds: int = 5,
) -> list[tuple[Path, float, float]]:
    """
    Split audio into overlapping chunks using ffmpeg.

    Returns:
        list of tuples: (chunk_path, chunk_start_sec, chunk_end_sec)
    """
    if chunk_seconds <= 0:
        raise ValueError("chunk_seconds must be > 0")
    if overlap_seconds < 0:
        raise ValueError("overlap_seconds must be >= 0")
    if overlap_seconds >= chunk_seconds:
        raise ValueError("overlap_seconds must be smaller than chunk_seconds")

    duration = get_audio_duration_seconds(audio_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    stride = chunk_seconds - overlap_seconds
    chunks: list[tuple[Path, float, float]] = []

    start = 0.0
    index = 0
    while start < duration:
        end = min(start + chunk_seconds, duration)
        chunk_path = output_dir / f"chunk_{index:04d}_{int(start):07d}s.wav"

        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(audio_path),
            "-t",
            f"{end - start:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(chunk_path),
        ]
        _run(cmd)

        chunks.append((chunk_path, start, end))
        start += stride
        index += 1

    return chunks



def build_model(
    model_size: str,
    device: str,
    compute_type: str,
):
    if WhisperModel is None:
        raise RuntimeError(
            "faster-whisper is not installed.\n"
            "Install it with: pip install faster-whisper"
        )
    return WhisperModel(model_size, device=device, compute_type=compute_type)


def transcribe_chunk(
    model,
    chunk_path: Path,
    chunk_start_sec: float,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Transcribe one chunk and shift segment timestamps so they align
    to the full original audio.
    """
    segments, info = model.transcribe(
        str(chunk_path),
        vad_filter=False,
        beam_size=5,
        language="en",
    )

    segment_dicts: list[dict[str, Any]] = []
    full_text_parts: list[str] = []

    for seg in segments:
        text = seg.text.strip()
        if text:
            full_text_parts.append(text)

        segment_dicts.append(
            {
                "start": float(seg.start) + chunk_start_sec,
                "end": float(seg.end) + chunk_start_sec,
                "text": text,
            }
        )

    return " ".join(full_text_parts).strip(), segment_dicts



def load_processed_videos(processed_json_path: Path) -> list[dict[str, Any]]:
    with processed_json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("processed videos JSON must be a list of video objects")

    return data


def process_downloaded_videos(
    processed_json_path: Path,
    testing_dir: Path,
    chunk_seconds: int,
    overlap_seconds: int,
    model_size: str,
    device: str,
    compute_type: str,
) -> None:
    check_ffmpeg_tools()

    videos = load_processed_videos(processed_json_path)
    downloaded_videos = [v for v in videos if v.get("status") == "downloaded"]

    if not downloaded_videos:
        print("No videos with status='downloaded' were found.")
        return

    print(f"Found {len(downloaded_videos)} downloaded video(s).")
    model = build_model(model_size=model_size, device=device, compute_type=compute_type)
    print(f"Using Whisper model with device={device}, compute_type={compute_type}, model_size={model_size}")
    
    for video in downloaded_videos:
        video_id = video.get("video_id", "unknown_video")
        audio_path = Path(video["audio_path"])

        if not audio_path.exists():
            print(f"[SKIP] Missing audio file for {video_id}: {audio_path}")
            continue

        video_dir = testing_dir / video_id
        chunks_dir = video_dir / "chunks"
        transcripts_dir = video_dir / "transcripts"
        transcripts_dir.mkdir(parents=True, exist_ok=True)

        print(f"\nProcessing {video_id}")
        print(f"Audio: {audio_path}")

        chunks = make_audio_chunks(
            audio_path=audio_path,
            output_dir=chunks_dir,
            chunk_seconds=chunk_seconds,
            overlap_seconds=overlap_seconds,
        )
        print(f"Created {len(chunks)} chunk(s) in {chunks_dir}")

        all_results: list[ChunkResult] = []

        for idx, (chunk_path, start_sec, end_sec) in enumerate(chunks):
            print(f"  Transcribing chunk {idx + 1}/{len(chunks)}: {chunk_path.name}")
            text, segments = transcribe_chunk(
                model=model,
                chunk_path=chunk_path,
                chunk_start_sec=start_sec,
            )

            result = ChunkResult(
                chunk_index=idx,
                chunk_path=str(chunk_path),
                start_sec=start_sec,
                end_sec=end_sec,
                text=text,
                segments=segments,
            )
            all_results.append(result)

            chunk_json_path = transcripts_dir / f"chunk_{idx:04d}.json"
            with chunk_json_path.open("w", encoding="utf-8") as f:
                json.dump(asdict(result), f, indent=2, ensure_ascii=False)

        joined_text = "\n\n".join(
            r.text for r in all_results if r.text.strip()
        )

        merged_segments: list[dict[str, Any]] = []
        for result in all_results:
            merged_segments.extend(result.segments)

        full_json = {
            "video_id": video_id,
            "title": video.get("title"),
            "audio_path": str(audio_path),
            "chunk_seconds": chunk_seconds,
            "overlap_seconds": overlap_seconds,
            "model_size": model_size,
            "device": device,
            "compute_type": compute_type,
            "full_text": joined_text,
            "segments": merged_segments,
            "chunks": [asdict(r) for r in all_results],
        }
        safe_title = sanitize_filename(video.get("title"))
        file_stem = f"{safe_title} [{video_id}]"

        full_json_path = OUTPUT_DIR / "transcripts" / video.get("classification") / f"{file_stem}.json"
        full_txt_path = OUTPUT_DIR / "transcripts" / video.get("classification") / f"{file_stem}.txt"
        full_txt_path.parent.mkdir(parents=True, exist_ok=True)
        full_json_path.parent.mkdir(parents=True, exist_ok=True)
        
        with full_json_path.open("w", encoding="utf-8") as f:
            json.dump(full_json, f, indent=2, ensure_ascii=False)

        with full_txt_path.open("w", encoding="utf-8") as f:
            f.write(joined_text)

        print(f"Saved transcript JSON: {full_json_path}")
        print(f"Saved transcript TXT : {full_txt_path}")

        print("Writing to database")

        if not full_json_path.exists():
            print(f"File not found: {full_json_path}")
            raise SystemExit(1)
        try:
            with SessionLocal() as session:
                video_db_id, action = ingest_transcript_json(session, full_json_path)

            print(f"{action.title()} transcript successfully. video row id = {video_db_id}")
            
            with SessionLocal() as session:
                video_count = session.scalar(select(func.count()).select_from(Video))
                transcript_count = session.scalar(select(func.count()).select_from(Transcript))
                segment_count = session.scalar(select(func.count()).select_from(TranscriptSegment))
                chunk_count = session.scalar(select(func.count()).select_from(TranscriptChunk))

                print("videos:", video_count)
                print("transcripts:", transcript_count)
                print("segments:", segment_count)
                print("chunks:", chunk_count)
            testing_dir = TESTING_DIR / f"{video_id}"
            if testing_dir.exists():
                shutil.rmtree(testing_dir)
                print(f"Deleted testing directory: {testing_dir}")
            
            if audio_path.exists():
                audio_path.unlink()
                print(f"Deleted audio file: {audio_path}")

            removed = remove_video_from_json(PROCESSED_FILE, video_id)
            
            load_dotenv()
            gdrive_enabled = os.getenv("GOOGLE_DRIVE_UPLOAD_ENABLED", "false").lower() == "true"
            gdrive_auth_mode = os.getenv("GOOGLE_DRIVE_AUTH_MODE", "oauth")
            drive_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
            oauth_client_json = os.getenv("GOOGLE_DRIVE_OAUTH_CLIENT_JSON")
            oauth_token_json = os.getenv("GOOGLE_DRIVE_OAUTH_TOKEN_JSON")
            service_account_json = os.getenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON")
            committee_code= video.get("classification")

            if gdrive_enabled:
                try:
                    uploaded = upload_transcript_files_to_drive(
                        json_path=full_json_path,
                        txt_path=full_txt_path,
                        drive_root_folder_id=drive_id,
                        committee_code=committee_code,
                        auth_mode=gdrive_auth_mode,
                        oauth_client_json_path=oauth_client_json,
                        token_json_path=oauth_token_json,
                        service_account_json_path=service_account_json,
                    )
                    print(f"Uploaded transcript files to Google Drive: {uploaded}")
                except Exception as exc:
                    print(f"Google Drive upload failed for{video_id}: {exc}")
        except Exception as exc:
            print(f"Database ingest failed for {full_json_path}: {exc}")
            raise




    print("\nDone.")


def _build_drive_service_service_account(service_account_json_path: str | Path):
    credentials = service_account.Credentials.from_service_account_file(
        str(service_account_json_path),
        scopes=DRIVE_SCOPES,
    )
    return build("drive", "v3", credentials=credentials)


def _build_drive_service_oauth(
    oauth_client_json_path: str | Path,
    token_json_path: str | Path,
):
    oauth_client_json_path = Path(oauth_client_json_path)
    token_json_path = Path(token_json_path)

    creds: UserCredentials | None = None

    if token_json_path.exists():
        creds = UserCredentials.from_authorized_user_file(
            str(token_json_path),
            scopes=DRIVE_SCOPES,
        )

    if creds is None or not creds.valid:
        if creds is not None and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(oauth_client_json_path),
                scopes=DRIVE_SCOPES,
            )
            creds = flow.run_local_server(port=0)

        token_json_path.parent.mkdir(parents=True, exist_ok=True)
        token_json_path.write_text(creds.to_json(), encoding="utf-8")

    return build("drive", "v3", credentials=creds)


def _escape_drive_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _get_or_create_subfolder(
    service,
    parent_folder_id: str,
    folder_name: str,
    auth_mode: AuthMode,
) -> str:
    escaped_folder_name = _escape_drive_query_value(folder_name)

    query = (
        f"'{parent_folder_id}' in parents and "
        f"name = '{escaped_folder_name}' and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false"
    )

    list_kwargs = {
        "q": query,
        "fields": "files(id, name)",
        "pageSize": 10,
    }

    if auth_mode == "service_account":
        list_kwargs["supportsAllDrives"] = True
        list_kwargs["includeItemsFromAllDrives"] = True

    response = service.files().list(**list_kwargs).execute()
    files = response.get("files", [])

    if files:
        return files[0]["id"]

    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }

    create_kwargs = {
        "body": metadata,
        "fields": "id, name",
    }

    if auth_mode == "service_account":
        create_kwargs["supportsAllDrives"] = True

    created = service.files().create(**create_kwargs).execute()
    return created["id"]


def _upload_one_file(
    service,
    file_path: Path,
    mime_type: str,
    drive_folder_id: str,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    metadata = {
        "name": file_path.name,
        "parents": [drive_folder_id],
    }

    media = MediaFileUpload(
        filename=str(file_path),
        mimetype=mime_type,
        resumable=True,
    )

    create_kwargs = {
        "body": metadata,
        "media_body": media,
        "fields": "id, name, webViewLink",
    }

    if auth_mode == "service_account":
        create_kwargs["supportsAllDrives"] = True

    created = service.files().create(**create_kwargs).execute()

    return {
        "id": created["id"],
        "name": created["name"],
        "webViewLink": created.get("webViewLink"),
    }


def upload_transcript_files_to_drive(
    json_path: str | Path,
    txt_path: str | Path,
    drive_root_folder_id: str,
    committee_code: str,
    auth_mode: AuthMode,
    oauth_client_json_path: str | Path | None = None,
    token_json_path: str | Path | None = None,
    service_account_json_path: str | Path | None = None,
) -> dict[str, Any]:
    json_path = Path(json_path)
    txt_path = Path(txt_path)

    if not json_path.exists():
        raise FileNotFoundError(f"JSON file not found: {json_path}")
    if not txt_path.exists():
        raise FileNotFoundError(f"TXT file not found: {txt_path}")
    if not drive_root_folder_id:
        raise ValueError("drive_root_folder_id is required")
    if not committee_code:
        raise ValueError("committee_code is required")

    if auth_mode == "oauth":
        if not oauth_client_json_path:
            raise ValueError("oauth_client_json_path is required for oauth mode")
        if not token_json_path:
            raise ValueError("token_json_path is required for oauth mode")

        service = _build_drive_service_oauth(
            oauth_client_json_path=oauth_client_json_path,
            token_json_path=token_json_path,
        )

    elif auth_mode == "service_account":
        if not service_account_json_path:
            raise ValueError(
                "service_account_json_path is required for service_account mode"
            )

        service = _build_drive_service_service_account(service_account_json_path)

    else:
        raise ValueError(f"Unsupported auth_mode: {auth_mode}")

    committee_folder_id = _get_or_create_subfolder(
        service=service,
        parent_folder_id=drive_root_folder_id,
        folder_name=committee_code,
        auth_mode=auth_mode,
    )

    results: dict[str, dict[str, Any]] = {}

    uploads = [
        (json_path, "application/json"),
        (txt_path, "text/plain"),
    ]

    for file_path, mime_type in uploads:
        results[file_path.name] = _upload_one_file(
            service=service,
            file_path=file_path,
            mime_type=mime_type,
            drive_folder_id=committee_folder_id,
            auth_mode=auth_mode,
        )

    return {
        "committee_folder_id": committee_folder_id,
        "committee_folder_name": committee_code,
        "files": results,
    }


def sanitize_filename(title: str) -> str:
    # Replace invalid characters with underscore
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', title)

    # Remove newlines and tabs
    sanitized = sanitized.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')

    # Collapse multiple spaces into one
    sanitized = re.sub(r'\s+', ' ', sanitized)

    # Strip leading/trailing whitespace
    sanitized = sanitized.strip()

    # Remove trailing dots or spaces (Windows issue)
    sanitized = sanitized.rstrip(' .')

    return sanitized


def transcribe_driver() -> None:
    # Model configurations avalible in .env, see .env.example
    # Chunk size in seconds. Default: 600 (10 minutes).
    # Overlap between chunks in seconds. Default: 5.
    # faster-whisper model size, e.g. tiny, base, small, medium, large-v3. Default: small
    # Device for faster-whisper: auto, cpu, or cuda. Default: Cuda, change to auto if no GPU
    # Compute type for faster-whisper, e.g. int8, int8_float16, float16, float32. Default: int8
    os.environ.get("CHANNEL_ID")
    process_downloaded_videos(
        processed_json_path=PROCESSED_FILE,
        testing_dir=TESTING_DIR,
        chunk_seconds=int(os.environ.get("CHUNK_SECONDS")),
        overlap_seconds=int(os.environ.get("OVERLAP_SECONDS")),
        model_size= os.environ.get("MODEL_SIZE"),
        device=os.environ.get("DEVICE"),
        compute_type= os.environ.get("COMPUTE_TYPE"),
    )


