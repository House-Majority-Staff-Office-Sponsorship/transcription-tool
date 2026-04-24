import time
import os
from datetime import datetime, timezone, timedelta
from src.transcription_tool.getUploads import getNewVideos, setup_logging
from src.transcription_tool.download_audio import process_pending_videos
from src.transcription_tool.transcribe_driver import transcribe_driver
from src.db.init_db import start_db
from dotenv import load_dotenv

load_dotenv()
try:
    POLL_INTERVAL_SECONDS = float(os.environ.get("POLL_INTERVAL_SECONDS", "600"))
except ValueError:
    raise RuntimeError("POLL_INTERVAL_SECONDS must be a valid number")

if POLL_INTERVAL_SECONDS <= 0:
    raise RuntimeError("POLL_INTERVAL_SECONDS must be greater than 0")

def main():
    start_db()
    logger = setup_logging()
    try:
        while True:
            cycle_start = time.time()
            try:
                getNewVideos()
                logger.info("Polling YouTube for new videos")
            except Exception as exc:
                print(f"getNewVideos failed: {exc}")
                logger.error(f"getNewVideos failed: {exc}")

            try:
                process_pending_videos()
            except Exception as exc:
                print(f"process_pending_videos failed: {exc}")
                logger.error(f"process_pending_videos failed: {exc}")

            try:
                transcribe_driver()
            except Exception as exc:
                print(f"transcribe_driver failed: {exc}")
                logger.error(f"transcribe_driver failed: {exc}")

            elapsed = time.time() - cycle_start
            sleep_seconds = max(0, POLL_INTERVAL_SECONDS - elapsed)

            hawaii = timezone(timedelta(hours=-10))
            now = datetime.now(hawaii)
            current_time = now.strftime("%H:%M:%S")

            print(
                f"[{current_time}] Cycle finished in {elapsed:.1f}s. "
                f"Sleeping for {sleep_seconds:.1f}s."
            )
            logger.info(
                f"[{current_time}] Cycle finished in {elapsed:.1f}s. "
                f"Sleeping for {sleep_seconds:.1f}s."
            )
            time.sleep(sleep_seconds)

    except KeyboardInterrupt:
        print("Polling loop stopped.")
        logger.info("Polling loop stopped, exiting program")

if __name__ == "__main__":
    main()

