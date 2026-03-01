import os
import time
import yt_dlp
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

class RequestData(BaseModel):
    video_url: str
    topic: str

class TimestampResponse(BaseModel):
    timestamp: str
    video_url: str
    topic: str

def cleanup_file(filepath: str):
    if os.path.exists(filepath):
        os.remove(filepath)

@app.post("/ask", response_model=TimestampResponse)
async def find_timestamp(data: RequestData, background_tasks: BackgroundTasks):
    video_url = data.video_url
    topic = data.topic
    
    # Use a shorter temp name to avoid file system issues
    temp_name = f"vid_{int(time.time())}"
    actual_audio_path = f"{temp_name}.mp3"

    # STEP 1: Robust Audio Download
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128', # Lower quality = smaller file = faster upload
        }],
        'outtmpl': temp_name,
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        # STEP 2: Upload to Gemini Files API
        print(f"Uploading {actual_audio_path}...")
        uploaded_file = client.files.upload(file=actual_audio_path)

        # STEP 3: Patient Polling (Required for long videos)
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(5) # Poll every 5 seconds for long files
            uploaded_file = client.files.get(name=uploaded_file.name)

        if uploaded_file.state.name == "FAILED":
            raise Exception("Gemini audio processing failed.")

        # STEP 4: High-Precision Prompting
        # We tell the AI the video is long and we need the EXACT phrase
        prompt = (
            f"This audio file is very long. Search the ENTIRE duration. "
            f"Find the EXACT timestamp where the speaker says: '{topic}'. "
            f"You MUST return the timestamp in HH:MM:SS format. "
            f"If it happens multiple times, provide the FIRST occurrence."
        )

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[uploaded_file, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TimestampResponse,
                temperature=0.0, # Zero temperature = most accurate/least creative
            ),
        )

        # Clean up
        client.files.delete(name=uploaded_file.name)
        background_tasks.add_task(cleanup_file, actual_audio_path)

        return response.parsed

    except Exception as e:
        if os.path.exists(actual_audio_path): cleanup_file(actual_audio_path)
        return {"timestamp": "00:00:00", "video_url": video_url, "topic": topic, "error": str(e)}
