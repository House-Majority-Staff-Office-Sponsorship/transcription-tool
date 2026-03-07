
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

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
# ----------------------------
# Data containers
# ----------------------------

@dataclass
class ChunkResult:
    chunk_index: int
    chunk_path: str
    start_sec: float
    end_sec: float
    text: str
    segments: list[dict[str, Any]]


# ----------------------------
# FFmpeg helpers
# ----------------------------

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
        chunk_path = output_dir / f"chunk_{index:04d}_{int(start):07d}s.mp3"

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
            "-acodec",
            "libmp3lame",
            "-q:a",
            "2",
            str(chunk_path),
        ]
        _run(cmd)

        chunks.append((chunk_path, start, end))
        start += stride
        index += 1

    return chunks


# ----------------------------
# Whisper helpers
# ----------------------------

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
        vad_filter=True,
        beam_size=5,
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


# ----------------------------
# Driver logic
# ----------------------------

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

        full_json_path = video_dir / f"{video_id}_transcript.json"
        full_txt_path = video_dir / f"{video_id}_transcript.txt"

        with full_json_path.open("w", encoding="utf-8") as f:
            json.dump(full_json, f, indent=2, ensure_ascii=False)

        with full_txt_path.open("w", encoding="utf-8") as f:
            f.write(joined_text)

        print(f"Saved transcript JSON: {full_json_path}")
        print(f"Saved transcript TXT : {full_txt_path}")

    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chunk downloaded audio files and transcribe them with faster-whisper."
    )
    parser.add_argument(
        "--processed-json",
        type=Path,
        default=Path("tempdata/processed_videos.json"),
        help="Path to the processed videos JSON file.",
    )
    parser.add_argument(
        "--testing-dir",
        type=Path,
        default=Path("tempdata/testing"),
        help="Directory where test chunks and transcripts will be written.",
    )
    parser.add_argument(
        "--chunk-seconds",
        type=int,
        default=600,
        help="Chunk size in seconds. Default: 600 (10 minutes).",
    )
    parser.add_argument(
        "--overlap-seconds",
        type=int,
        default=5,
        help="Overlap between chunks in seconds. Default: 5.",
    )
    parser.add_argument(
        "--model-size",
        type=str,
        default="small",
        help="faster-whisper model size, e.g. tiny, base, small, medium, large-v3.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help="Device for faster-whisper: auto, cpu, or cuda.",
    )
    parser.add_argument(
        "--compute-type",
        type=str,
        default="int8",
        help="Compute type for faster-whisper, e.g. int8, int8_float16, float16, float32.",
    )
    

    process_downloaded_videos(
        processed_json_path=PROCESSED_FILE,
        testing_dir=TESTING_DIR,
        chunk_seconds=600,
        overlap_seconds=5,
        model_size= "small",
        device="cuda",
        compute_type= "int8_float16",
    )


