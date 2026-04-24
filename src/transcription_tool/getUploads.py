import json
import logging
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from googleapiclient.discovery import build

DATA_DIR = Path("tempdata")
DATA_DIR.mkdir(exist_ok=True)

STATE_DIR = Path("state")
STATE_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = STATE_DIR / Path("youtube_state.json")
PLAYLIST_CACHE_FILE = STATE_DIR / Path("youtube_playlist_cache.json")
PENDING_VIDEOS_FILE = STATE_DIR / Path("pending_videos.json")

logger = logging.getLogger(__name__)

def load_json(path: Path):
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2))


def get_uploads_playlist_id(youtube, channel_id: str) -> str:
    resp = youtube.channels().list(
        part="contentDetails",
        id=channel_id,
        maxResults=1,
    ).execute()

    items = resp.get("items", [])
    if not items:
        raise ValueError("No channel found for given channel id")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_or_fetch_uploads_playlist_id(youtube, channel_id: str) -> str:
    cache = load_json(PLAYLIST_CACHE_FILE)

    if channel_id in cache:
        return cache[channel_id]

    uploads_id = get_uploads_playlist_id(youtube, channel_id)
    cache[channel_id] = uploads_id
    save_json(PLAYLIST_CACHE_FILE, cache)
    return uploads_id


def poll_uploads_playlist_for_new_video_ids(
    youtube,
    uploads_playlist_id: str,
    last_seen_video_id: Optional[str],
    max_results: int = 50,
) -> list[str]:

    resp = youtube.playlistItems().list(
        part="contentDetails",
        playlistId=uploads_playlist_id,
        maxResults=max_results,
    ).execute()

    items = resp.get("items", [])

    new_ids: list[str] = []
    for it in items:
        vid = it["contentDetails"]["videoId"]
        if last_seen_video_id and vid == last_seen_video_id:
            break
        new_ids.append(vid)

    # playlistItems are newest -> oldest, reverse so we process oldest -> newest
    new_ids.reverse()
    return new_ids


def fetch_video_metadata(youtube, video_ids: list[str]) -> list[dict]:
    if not video_ids:
        return []

    resp = youtube.videos().list(
        part="snippet,contentDetails,statistics,liveStreamingDetails,status",
        id=",".join(video_ids),
        maxResults=len(video_ids),
    ).execute()

    return resp.get("items", [])


def build_queue_entry(v: dict) -> dict:
    snippet = v.get("snippet", {})
    content = v.get("contentDetails", {})
    live = v.get("liveStreamingDetails", {})

    return {
        "video_id": v["id"],
        "title": snippet.get("title"),
        "published_at": snippet.get("publishedAt"),
        "duration": content.get("duration"),
        "live_status": snippet.get("liveBroadcastContent"),
        "actual_start_time": live.get("actualStartTime"),
        "actual_end_time": live.get("actualEndTime"),
        "status": "pending",
    }


def upsert_videos_in_queue(videos: list[dict]):
    queue = load_json(PENDING_VIDEOS_FILE)

    if not isinstance(queue, list):
        queue = []

    queue_by_id = {
        v["video_id"]: v
        for v in queue
        if isinstance(v, dict) and "video_id" in v
    }

    added = 0
    updated = 0

    for v in videos:
        vid = v["id"]
        new_entry = build_queue_entry(v)

        if vid in queue_by_id:
            old_entry = queue_by_id[vid]

            old_live_status = old_entry.get("live_status")
            new_live_status = new_entry.get("live_status")

            # preserve any downstream processing status unless you want to reset it
            new_entry["status"] = old_entry.get("status", "pending")

            queue_by_id[vid] = new_entry
            updated += 1

            if old_live_status != new_live_status:
                print(
                    f"Updated live_status for {vid}: "
                    f"{old_live_status} -> {new_live_status}"
                )
        else:
            queue_by_id[vid] = new_entry
            added += 1

    new_queue = list(queue_by_id.values())
    save_json(PENDING_VIDEOS_FILE, new_queue)

    print(f"Queue updated: {added} added, {updated} refreshed")
    logger.info(f"Queue updated: {added} added, {updated} refreshed")


def refresh_pending_live_videos(youtube):
    queue = load_json(PENDING_VIDEOS_FILE)

    if not isinstance(queue, list):
        queue = []

    refresh_ids = []
    for v in queue:
        if not isinstance(v, dict):
            continue

        # only re-check videos that are still live/upcoming
        live_status = v.get("live_status")
        status = v.get("status", "pending")

        # optional: only refresh entries that are still pending
        if status == "pending" and live_status != "none":
            refresh_ids.append(v["video_id"])

    if not refresh_ids:
        print("No pending live/upcoming videos to refresh.")
        logger.info("No pending live/upcoming videos to refresh.")
        return

    print(f"Refreshing {len(refresh_ids)} pending live/upcoming video(s):", refresh_ids)

    refreshed_items = fetch_video_metadata(youtube, refresh_ids)
    upsert_videos_in_queue(refreshed_items)

def setup_logging(log_dir: str = "data/logs", log_name: str = "transcription_tool.log") -> logging.Logger:
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("transcription_tool")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_path / log_name,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def getNewVideos():
    load_dotenv()

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        raise RuntimeError("Youtube API key is not set check the .env variables")

    youtube = build("youtube", "v3", developerKey=api_key)
    channel_id = os.environ.get("CHANNEL_ID")

    uploads_playlist_id = get_or_fetch_uploads_playlist_id(youtube, channel_id)
    print("Uploads playlist:", uploads_playlist_id)

    state = load_json(STATE_FILE)
    last_seen = state.get(channel_id, {}).get("last_seen_video_id")
    max_videos = int(os.environ.get("MAX_VIDEOS"))

    # First: refresh old pending live/upcoming videos
    refresh_pending_live_videos(youtube)

    # Then: look for truly new videos since last_seen
    new_video_ids = poll_uploads_playlist_for_new_video_ids(
        youtube,
        uploads_playlist_id=uploads_playlist_id,
        last_seen_video_id=last_seen,
        max_results=max_videos,
    )

    if not new_video_ids:
        print("No new videos.")
        logger.info("No new videos")
        return

    print(f"Found {len(new_video_ids)} new video(s):", new_video_ids)
    logger.info(f"Found {len(new_video_ids)} new video(s):", new_video_ids)
    items = fetch_video_metadata(youtube, new_video_ids)

    # add new ones, and if somehow already present, refresh them in place
    upsert_videos_in_queue(items)

    for v in items:
        vid = v["id"]
        sn = v.get("snippet", {})
        cd = v.get("contentDetails", {})
        live = v.get("liveStreamingDetails", {})
        stats = v.get("statistics", {})
        status = v.get("status", {})

        print(
            sn.get("publishedAt"),
            vid,
            sn.get("title"),
            cd.get("duration"),
            sn.get("liveBroadcastContent"),
            "views=" + stats.get("viewCount", "NA"),
            "privacy=" + status.get("privacyStatus", "NA"),
            "liveStart=" + str(live.get("actualStartTime", "NA")),
            "liveEnd=" + str(live.get("actualEndTime", "NA")),
        )

    # keep last_seen meaning: newest playlist item we've already noticed
    newest_id = new_video_ids[-1]
    state.setdefault(channel_id, {})["last_seen_video_id"] = newest_id
    save_json(STATE_FILE, state)
    print("Updated last_seen_video_id:", newest_id)
    logger.info("Updated last_seen_video_id:", newest_id)