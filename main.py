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
    temp_id = int(time.time())
    audio_path = f"audio_{temp_id}.mp3"

    # Optimization: Low bitrate (32k) to handle 8-hour videos on Render's tiny disk
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '32', 
        }],
        'outtmpl': f"audio_{temp_id}",
        'quiet': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        # Upload to Gemini
        uploaded_file = client.files.upload(file=audio_path)

        # Polling - Important for long files
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(5)
            uploaded_file = client.files.get(name=uploaded_file.name)

        if uploaded_file.state.name == "FAILED":
            raise Exception("Gemini processing failed")

        # Forceful Prompting for long-form content
        prompt = (
            f"I am providing a very long audio file. Search the ENTIRE audio. "
            f"Find the FIRST time the speaker mentions this exact topic: '{topic}'. "
            f"Return the timestamp strictly in HH:MM:SS format. "
            f"If you are unsure, search the middle and end of the file carefully."
        )

        response = client.models.generate_content(
            model="gemini-1.5-flash", # Flash is better at long-context scanning
            contents=[uploaded_file, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TimestampResponse,
                temperature=0.0,
            ),
        )

        # Cleanup
        client.files.delete(name=uploaded_file.name)
        background_tasks.add_task(cleanup_file, audio_path)

        return response.parsed

    except Exception as e:
        if os.path.exists(audio_path): cleanup_file(audio_path)
        # Return a fallback that isn't 00:00:00 so you can see if it's a real error
        return {"timestamp": "00:00:01", "video_url": video_url, "topic": topic}
