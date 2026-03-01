import os
import time
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
import yt_dlp
from google import genai
from google.genai import types

app = FastAPI()

# 1. New SDK Initialization
# We use an environment variable for security
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

# 2. Schema for Structured Output
class TimestampResponse(BaseModel):
    timestamp: str  # Format: HH:MM:SS
    video_url: str
    topic: str

class RequestData(BaseModel):
    video_url: str
    topic: str

def cleanup_file(filepath: str):
    if os.path.exists(filepath):
        os.remove(filepath)

@app.post("/ask", response_model=TimestampResponse)
async def find_timestamp(data: RequestData, background_tasks: BackgroundTasks):
    video_url = data.video_url
    topic = data.topic
    temp_filename = f"audio_{int(time.time())}.mp3"

    # Download Audio with yt-dlp
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': temp_filename,
        'quiet': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        # yt-dlp might ensure the extension is .mp3
        actual_path = temp_filename if os.path.exists(temp_filename) else f"{temp_filename}.mp3"

        # 3. Upload via New Files API
        uploaded_file = client.files.upload(file=actual_path)

        # 4. Polling for 'ACTIVE' state
        while uploaded_file.state == "PROCESSING":
            time.sleep(2)
            uploaded_file = client.files.get(name=uploaded_file.name)

        # 5. Ask Gemini using Structured Outputs
        prompt = (
            f"Pinpoint the first time '{topic}' is mentioned in this audio. "
            "Return the answer strictly in HH:MM:SS format."
        )

        response = client.models.generate_content(
            model="gemini-2.0-flash", # Or 'gemini-1.5-pro'
            contents=[uploaded_file, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TimestampResponse,
            ),
        )

        # Delete from Gemini server after use (best practice)
        client.files.delete(name=uploaded_file.name)
        
        # Schedule local file cleanup
        background_tasks.add_task(cleanup_file, actual_path)

        return response.parsed

    except Exception as e:
        if 'actual_path' in locals(): cleanup_file(actual_path)
        return {"error": str(e)}
