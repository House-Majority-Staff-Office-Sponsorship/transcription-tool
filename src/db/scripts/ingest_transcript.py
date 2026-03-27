from pathlib import Path

from db.repository import ingest_transcript_json
from db.session import SessionLocal
from db.models import Video, Transcript, TranscriptSegment, TranscriptChunk
from sqlalchemy import select, func


def ingest(path: Path) -> None:
    transcript_json_path = path
    if not transcript_json_path.exists():
        print(f"File not found: {transcript_json_path}")
        raise SystemExit(1)

    with SessionLocal() as session:
        video_db_id, action = ingest_transcript_json(session, transcript_json_path)

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

