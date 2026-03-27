from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

APPROVED_COMMITTEES = {
    "CPC", "HLT", "FIN", "EEP", "HSG", "HSH", "CAA", "AGR", "WAL",
    "JHA", "EDU", "HED", "ECD", "LAB", "PBS", "TRN", "TOU", "LMG"
}

DATA_DIR = Path("tempdata")
DATA_DIR.mkdir(parents=True, exist_ok=True)

PENDING_FILE = DATA_DIR / "pending_videos.json"
PROCESSED_FILE = DATA_DIR / "processed_videos.json"
FAILED_FILE = DATA_DIR / "failed_downloads.json"
AUDIO_DIR = DATA_DIR / "audio"

# Setup all our directories for storing data temporaraly while videos are being processed
def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    (AUDIO_DIR / "JOINT").mkdir(parents=True, exist_ok=True)
    (AUDIO_DIR / "UNCLASSIFIED").mkdir(parents=True, exist_ok=True)

    for committee in APPROVED_COMMITTEES:
        (AUDIO_DIR / committee).mkdir(parents=True, exist_ok=True)

# Helpers to load and save json files
def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            return []
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list.")
    return data


def save_json_list(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def append_json_record(path: Path, record: dict[str, Any]) -> None:
    data = load_json_list(path)
    data.append(record)
    save_json_list(path, data)


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip())


def classify_title(title: str) -> dict[str, Any]:
    normalized = normalize_title(title)
    if not normalized:
        return {
            "classification": "UNCLASSIFIED",
            "is_joint": False,
            "joint_committees": [],
        }

    first_token = normalized.split(" ", 1)[0].upper()

    joint_match = re.fullmatch(r"([A-Z]{3})-([A-Z]{3})", first_token)
    if joint_match:
        c1, c2 = joint_match.groups()
        if c1 in APPROVED_COMMITTEES and c2 in APPROVED_COMMITTEES:
            return {
                "classification": "JOINT",
                "is_joint": True,
                "joint_committees": [c1, c2],
            }

    if first_token in APPROVED_COMMITTEES:
        return {
            "classification": first_token,
            "is_joint": False,
            "joint_committees": [],
        }

    return {
        "classification": "UNCLASSIFIED",
        "is_joint": False,
        "joint_committees": [],
    }


def build_youtube_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def already_processed(video_id: str) -> bool:
    processed = load_json_list(PROCESSED_FILE)
    return any(item.get("video_id") == video_id for item in processed)

# Uses yt-dlp and then runs a command line command to download the audio from our youtube link
def download_audio(video_id: str, classification: str) -> Path:
    output_dir = AUDIO_DIR / classification
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{video_id}.wav"
    url = build_youtube_url(video_id)

    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format", "wav",
        "--audio-quality", "0",
        "-o", str(output_dir / f"{video_id}.%(ext)s"),
        url,
    ]

    subprocess.run(cmd, check=True)
    return output_path

# main driver code 
def process_pending_videos() -> None:
    ensure_dirs() # setup our directories

    pending_videos = load_json_list(PENDING_FILE)
    remaining_pending: list[dict[str, Any]] = []

    for video in pending_videos:
        video_id = video.get("video_id")
        title = video.get("title", "")
        live_status = video.get("live_status")

        if not video_id:
            remaining_pending.append(video)
            continue

        # Leave live and upcoming videos in pending
        if live_status != "none":
            remaining_pending.append(video)
            continue

        # Already handled before: remove from pending
        if already_processed(video_id):
            continue

        classification_info = classify_title(title)
        classification = classification_info["classification"]

        try:
            audio_path = download_audio(video_id, classification)
        except subprocess.CalledProcessError as exc:
            failed_record = {
                "video_id": video_id,
                "title": title,
                "classification": classification,
                "is_joint": classification_info["is_joint"],
                "joint_committees": classification_info["joint_committees"],
                "error": str(exc),
                "status": "download_failed",
            }
            append_json_record(FAILED_FILE, failed_record)
            remaining_pending.append(video)
            continue

        processed_record = {
            "video_id": video_id,
            "title": title,
            "classification": classification,
            "is_joint": classification_info["is_joint"],
            "joint_committees": classification_info["joint_committees"],
            "audio_path": str(audio_path),
            "status": "downloaded",
        }
        append_json_record(PROCESSED_FILE, processed_record)

        # successful processing -> do not keep in pending

    save_json_list(PENDING_FILE, remaining_pending)

