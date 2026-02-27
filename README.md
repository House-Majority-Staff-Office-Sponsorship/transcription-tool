# transcription-tool
Overview: A  pipeline that downloads videos from a specified YouTube channel, transcribes the audio to text, classifies by committee and stores organized transcripts in the database/file system. The pipeline ("Transcription tool") would serve as a universally used service that would ensure that legislative proceedings are searchable and accessible from a central source. The tool's goal is to automate translating hours of video into a searchable, plain-text record for everyone from legislative staff to local constituents.

This project can be run both in python directly (recommended for development) as well as in Docker (used for testing and how the final project will be shipped). 

1. Build the image (the period at the end is important):
docker build -t transcription-tool . 

2. Run the project
docker run --rm transcription tool 

Current output for testing: transcription_tool: project scaffold OK


Runing with python

1. Create a python enviornment

With venv
python -m venv .venv

Activate:
Windows: 
.venv\Scripts\activate

macOS\Linux:
source .venv/bin/activate

Using Conda:
conda create -n transcription-tool python=3.10 -y
conda activate transcription-tool

2. Install Dependicies 
pip install -r requirements.txt

3. Run the project
python -m transcription-tool

Current output for testing: transcription_tool: project scaffold OK




