import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from googleapiclient.discovery import build

DATA_DIR = Path("tempdata")
DATA_DIR.mkdir(exist_ok=True)

STATE_FILE = DATA_DIR / Path("youtube_state.json")
PLAYLIST_CACHE_FILE = DATA_DIR / Path("youtube_playlist_cache.json")
PENDING_VIDEOS_FILE = DATA_DIR / Path("pending_videos.json")

#Helper functions for loading and saving data to a json file
def load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}

def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2))

def get_uploads_playlist_id(youtube, channel_id: str)-> str:
    resp = youtube.channels().list(
        part="contentDetails",
        id=channel_id,
        maxResults=1,
    ).execute()

    items = resp.get("items", [])
    if not items:
        raise ValueError("No channel found for given channel id")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

#add new videos to pending videos file without and duplicates
def append_new_videos_to_queue(videos: list[dict]):
    queue = load_json(PENDING_VIDEOS_FILE)

    if not isinstance(queue, list):
        queue = []

    existing_ids = {v["video_id"] for v in queue if "video_id" in v}

    new_entries = []

    for v in videos:
        vid = v["id"]

        if vid in existing_ids:
            continue

        snippet = v.get("snippet", {})
        content = v.get("contentDetails", {})
        live = v.get("liveStreamingDetails", {})

        entry = {
            "video_id": vid,
            "title": snippet.get("title"),
            "published_at": snippet.get("publishedAt"),
            "duration": content.get("duration"),
            "live_status": snippet.get("liveBroadcastContent"),
            "actual_start_time": live.get("actualStartTime"),
            "actual_end_time": live.get("actualEndTime"),
            "status": "pending"
        }

        new_entries.append(entry)

    if new_entries:
        queue.extend(new_entries)
        save_json(PENDING_VIDEOS_FILE, queue)
        print(f"Added {len(new_entries)} video(s) to pending_videos.json")
    else:
        print("No new videos added to queue")

def list_uploads(youtube, uploads_playlist_id: str, page_token: str | None = None, max_results: int = 50):
    resp = youtube.playlistItems().list(
        part="snippet,contentDetails",
        playlistId=uploads_playlist_id,
        maxResults=max_results,
        pageToken=page_token,
    ).execute()

    videos = []
    for video in resp.get("items", []):
        videos.append({
            "video_id": video["contentDetails"]["videoId"],
            "published_at": video["snippet"]["publishedAt"],
            "title": video["snippet"]["title"],
        })

    return videos, resp.get("nextPageToken")

def get_or_fetch_uploads_playlist_id(youtube, channel_id: str) -> str:
    cache = load_json(PLAYLIST_CACHE_FILE)

    if channel_id in cache:
        return cache[channel_id]

    uploads_id = get_uploads_playlist_id(youtube, channel_id)
    cache[channel_id] = uploads_id
    save_json(PLAYLIST_CACHE_FILE, cache)
    return uploads_id

#Checks for new videos in the playlist list 
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

    # playlistItems new->old reverse so we process oldest -> newest
    new_ids.reverse()
    return new_ids

#get the full metadata of our videos which we need to determine status and for future storage
def fetch_video_metadata(youtube, video_ids: list[str]) -> list[dict]:
    if not video_ids:
        return []

    resp = youtube.videos().list(
        part="snippet,contentDetails,statistics,liveStreamingDetails,status",
        id=",".join(video_ids),
        maxResults=len(video_ids),
    ).execute()

    return resp.get("items", [])


def main():

    load_dotenv()
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        raise RuntimeError("Youtube API key is not set check the .env variables")

    youtube = build("youtube", "v3", developerKey=api_key)
    #The channel ID is UCvoLAX1ww3e63K8qQ5of0bw, 
    # its not sensitive info its just stored in .env for organization
    channel_id = os.environ.get("CHANNEL_ID")

    uploads_playlist_id = get_or_fetch_uploads_playlist_id(youtube, channel_id)
    print("Uploads playlist:", uploads_playlist_id)

    # Load last seen state
    state = load_json(STATE_FILE)
    last_seen = state.get(channel_id, {}).get("last_seen_video_id")

    # Poll for new video IDs
    new_video_ids = poll_uploads_playlist_for_new_video_ids(
        youtube,
        uploads_playlist_id=uploads_playlist_id,
        last_seen_video_id=last_seen,
        max_results=50,
    )

    if not new_video_ids:
        print("No new videos.")
        return

    print(f"Found {len(new_video_ids)} new video(s):", new_video_ids)

    # Fetch rich metadata
    items = fetch_video_metadata(youtube, new_video_ids)

    append_new_videos_to_queue(items)

    # Print a useful subset
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
            "liveStart=" + live.get("actualStartTime", "NA"),
            "liveEnd=" + live.get("actualEndTime", "NA"),
        )

    # Update last_seen to newest ID we just processed
    # save our state for future useage. 
    newest_id = new_video_ids[-1]
    state.setdefault(channel_id, {})["last_seen_video_id"] = newest_id
    save_json(STATE_FILE, state)
    print("Updated last_seen_video_id:", newest_id)



