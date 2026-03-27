import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import (
    Transcript,
    TranscriptChunk,
    TranscriptSegment,
    Video,
)


def infer_classification_type(committee_code: str) -> str:
    if committee_code.upper() == "JOINT":
        return "joint"
    if committee_code.upper() == "UNCLASSIFIED":
        return "unclassified"
    return "committee"


def infer_committee_code_from_audio_path(audio_path: str) -> str:
    path = Path(audio_path)
    return path.parent.name


def _create_transcript_children(
    session: Session,
    transcript: Transcript,
    payload: dict,
) -> None:
    for idx, seg in enumerate(payload.get("segments", [])):
        session.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                segment_index=idx,
                start_seconds=seg["start"],
                end_seconds=seg["end"],
                text=seg["text"],
            )
        )

    for chunk in payload.get("chunks", []):
        session.add(
            TranscriptChunk(
                transcript_id=transcript.id,
                chunk_index=chunk["chunk_index"],
                chunk_path=chunk["chunk_path"],
                start_seconds=chunk["start_sec"],
                end_seconds=chunk["end_sec"],
                text=chunk["text"],
            )
        )


def ingest_transcript_json(session: Session, transcript_json_path: str | Path) -> int:
    transcript_json_path = Path(transcript_json_path)

    with transcript_json_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    youtube_video_id = payload["video_id"]
    title = payload["title"]
    audio_path = payload["audio_path"]

    committee_code = infer_committee_code_from_audio_path(audio_path)
    classification_type = infer_classification_type(committee_code)
    transcript_txt_path = transcript_json_path.with_suffix(".txt")

    existing_video = session.scalar(
        select(Video).where(Video.youtube_video_id == youtube_video_id)
    )

    if existing_video is None:
        action = "inserted"
        video = Video(
            youtube_video_id=youtube_video_id,
            title=title,
            committee_code=committee_code,
            classification_type=classification_type,
            audio_path=audio_path,
            transcript_txt_path=str(transcript_txt_path),
            transcript_json_path=str(transcript_json_path),
            status="completed",
            error_message=None,
        )
        session.add(video)
        session.flush()
    else:
        action = "updated"
        video = existing_video
        video.title = title
        video.committee_code = committee_code
        video.classification_type = classification_type
        video.audio_path = audio_path
        video.transcript_txt_path = str(transcript_txt_path)
        video.transcript_json_path = str(transcript_json_path)
        video.status = "completed"
        video.error_message = None

        for old_transcript in list(video.transcripts):
            session.delete(old_transcript)

        session.flush()

    transcript = Transcript(
        video_id=video.id,
        chunk_seconds=payload["chunk_seconds"],
        overlap_seconds=payload["overlap_seconds"],
        model_size=payload["model_size"],
        device=payload["device"],
        compute_type=payload["compute_type"],
        full_text=payload["full_text"],
    )
    session.add(transcript)
    session.flush()

    _create_transcript_children(session, transcript, payload)

    session.commit()
    return video.id, action