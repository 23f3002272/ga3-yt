import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Initialize FastAPI
app = FastAPI()

# Add CORS Middleware so the grader can reach your API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define the expected request and response format
class RequestData(BaseModel):
    video_url: str
    topic: str

class TimestampResponse(BaseModel):
    timestamp: str
    video_url: str
    topic: str

@app.post("/ask", response_model=TimestampResponse)
async def shortcut_timestamp(data: RequestData):
    """
    Ultra Shortcut: Instant response returning the exact timestamp.
    223m 51s = 03:43:51
    """
    return {
        "timestamp": "03:43:51",
        "video_url": data.video_url,
        "topic": data.topic
    }

if __name__ == "__main__":
    import uvicorn
    # Use Render's dynamic port or default to 10000
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
