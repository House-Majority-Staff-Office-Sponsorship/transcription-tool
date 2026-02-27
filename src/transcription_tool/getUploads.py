import os
from dotenv import load_dotenv
from googleapiclient.discovery import build



def get_uploads_playlist_id(youtube, channel_id: str)-> str:
    resp = youtube.channels().list(
        part="contentDetails",
        id=channel_id,
        maxResults=1,
    ).execute()

    items = resp.get("items", [])
    if not items:
        raise ValueError(f"No channel found for given channel id ")
    
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


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

def main():
    load_dotenv()
    YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    channel_id = "UCvoLAX1ww3e63K8qQ5of0bw"

    #uploads_playlist_id = get_uploads_playlist_id(youtube, channel_id)
    #print("Uploads Playlist Id: ", uploads_playlist_id)
    uploads_playlist_id = os.environ["UPLOADS_PLAYLIST_ID"]
    videos, next_token = list_uploads(youtube, uploads_playlist_id)

    for v in videos[:10]:
        print(v["published_at"], v["video_id"], v["title"])

