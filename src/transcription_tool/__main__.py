#Uncomment to try pulling data from YouTube
from src.transcription_tool.getUploads import main
from src.transcription_tool.download_audio import process_pending_videos
# def main():
#     print("transcription_tool: project scaffold OK")

if __name__ == "__main__":
    process_pending_videos()