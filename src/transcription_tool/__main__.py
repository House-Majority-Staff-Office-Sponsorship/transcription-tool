import time
import os
from src.transcription_tool.getUploads import getNewVideos
from src.transcription_tool.download_audio import process_pending_videos
from src.transcription_tool.transcribe_driver import transcribe_driver
from src.db.init_db import start_db
from dotenv import load_dotenv

load_dotenv()
POLL_INTERVAL_SECONDS = os.environ.get("POLL_INTERVAL_SECONDS")

def main():
    start_db()
    try:
        while True:
            cycle_start = time.time()
            try:
                getNewVideos()
            except Exception as exc:
                print(f"getNewVideos failed: {exc}")

            try:
                process_pending_videos()
            except Exception as exc:
                print(f"process_pending_videos failed: {exc}")

            try:
                transcribe_driver()
            except Exception as exc:
                print(f"transcribe_driver failed: {exc}")

            elapsed = time.time() - cycle_start
            sleep_seconds = max(0, POLL_INTERVAL_SECONDS - elapsed)

            print(
                f"Cycle finished in {elapsed:.1f}s. "
                f"Sleeping for {sleep_seconds:.1f}s."
            )

            time.sleep(sleep_seconds)

    except KeyboardInterrupt:
        print("Polling loop stopped.")


if __name__ == "__main__":
    main()

