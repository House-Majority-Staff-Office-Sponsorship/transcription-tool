# transcription-tool
<h2>Overview</h2>

A pipeline that downloads videos from a specified YouTube channel, transcribes the audio to text, classifies by committee, and stores organized transcripts in a database and file system.

The Transcription Tool is designed as a continuously running service that converts legislative video recordings into a searchable, plain-text format. This enables easier access to legislative proceedings for staff, researchers, and the public.

Setup Instructions: <br>
1. Clone the repository 
2. Go to <a href="https://cloud.google.com/cloud-console">Google Cloud Console</a>. 
3. Create a new project.
4. Enable the YouTube Data API v3.
5. Create Credentials -> API Key.
6. Setup the .env file by copying .env.example and placing your API key into the `YOUTUBE_API_KEY` field. Note that this API key is private and should not be shared, ensure your file is named .env before committing to github.
7. The `CHANNEL_ID` can be found on a YouTube channel's page by clicking "more" -> "Share Channel" -> "Copy Channel ID".

8. Build the image:
`docker build -t transcription-tool:dev .` 

9. Run the project:  
Option A (Basic run, no GPU, no mounted directory)  
 `docker run --rm transcription-tool:dev` <br>
Option B (Recommended, with GPU and mounted directory)  
 On LINUX/MAC: `docker run --rm --gpus all -v "$(pwd):/app" transcription-tool:dev`<br>
ON Windows (CMD) `docker run --rm --gpus all -v "%cd%:/app" transcription-tool:dev`  
---
<h2>How the project works</h2>
This project runs continously in a loop, in each cycle:  

1. The program checks for new videos on the upload playlist of the configured YouTube channel.  
2. Downloads the audio for each new video found in the upload playlist
3. Transcribes the audio using Whisper
4. Stores the metadata in the database and the `.json` and `.txt` files in `/data/transcripts/<comitee_classification>`.
