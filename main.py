import os
import time
import yt_dlp
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import types

# 1. Initialize FastAPI
app = FastAPI()

# 2. FIX: ADD CORS MIDDLEWARE
# This allows the validator or any website to call your API without being blocked.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)

# 3. Initialize Gemini Client (New google-genai library)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

# 4. Define Data Models (Schemas)
class RequestData(BaseModel):
    video_url: str
    topic: str

class TimestampResponse(BaseModel):
    timestamp: str  # Must be HH:MM:SS
    video_url: str
    topic: str

# 5. Helper Function for Cleanup
def cleanup_file(filepath: str):
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            print(f"Successfully deleted {filepath}")
        except Exception as e:
            print(f"Error deleting file: {e}")

# 6. The API Endpoint
@app.post("/ask", response_model=TimestampResponse)
async def find_timestamp(data: RequestData, background_tasks: BackgroundTasks):
    video_url = data.video_url
    topic = data.topic
    
    # Unique filename to avoid collisions
    temp_id = int(time.time())
    audio_filename = f"audio_{temp_id}.mp3"

    # STEP 1: Download Audio Only using yt-dlp
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': f"audio_{temp_id}", # yt-dlp adds the .mp3 automatically
        'quiet': True,
        'no_warnings': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        actual_path = f"audio_{temp_id}.mp3"

        # STEP 2: Upload to Gemini Files API
        print(f"Uploading {actual_path} to Gemini...")
        uploaded_file = client.files.upload(file=actual_path)

        # STEP 3: Wait for Gemini to process (Polling)
        while uploaded_file.state.name == "PROCESSING":
            print("Gemini is processing the audio...")
            time.sleep(3)
            uploaded_file = client.files.get(name=uploaded_file.name)

        if uploaded_file.state.name == "FAILED":
            raise Exception("Gemini audio processing failed.")

        # STEP 4: Ask Gemini to locate the topic
        # Note: Using the HH:MM:SS requirement in the prompt
        prompt = (
            f"You are a video search assistant. Listen to this audio and find the EXACT "
            f"time when the speaker mentions '{topic}'. "
            f"You MUST return the response in HH:MM:SS format (e.g., 00:04:12)."
        )

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[uploaded_file, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TimestampResponse,
            ),
        )

        # Clean up the file from Gemini's server (best practice)
        client.files.delete(name=uploaded_file.name)

        # Schedule local file cleanup for later
        background_tasks.add_task(cleanup_file, actual_path)

        # Return the parsed JSON object directly
        return response.parsed

    except Exception as e:
        # In case of error, still try to clean up
        if 'actual_path' in locals():
            background_tasks.add_task(cleanup_file, actual_path)
        return {"error": str(e), "timestamp": "00:00:00", "video_url": video_url, "topic": topic}

if __name__ == "__main__":
    import uvicorn
    # Use port 8000 for local testing or Render's dynamic port
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
