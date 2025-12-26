from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import uvicorn

app = FastAPI()

class WordTiming(BaseModel):
    word: str
    start: float
    end: float

class LineTiming(BaseModel):
    text: str
    start: Optional[float] = None
    end: Optional[float] = None

class ExtractResponse(BaseModel):
    text: str
    lines: List[LineTiming]
    words: Optional[List[WordTiming]] = None

@app.post("/extract-lyrics", response_model=ExtractResponse)
async def extract_lyrics(payload: dict):
    # Minimal stub: expects { audio_key: "..." }
    audio_key = payload.get("audio_key")
    if not audio_key:
        raise HTTPException(status_code=400, detail="Missing audio_key")

    # Placeholder behavior: return a few lines and approximate word timings
    text = "This is a placeholder lyric\nSinging along to the beat"
    lines = [
        {"text": "This is a placeholder lyric", "start": 0.0, "end": 4.0},
        {"text": "Singing along to the beat", "start": 4.0, "end": 8.0},
    ]

    words = []
    for ln in lines:
        words_in_line = ln["text"].split()
        dur = (ln["end"] - ln["start"]) / max(1, len(words_in_line))
        for i, w in enumerate(words_in_line):
            words.append({"word": w, "start": ln["start"] + i * dur, "end": ln["start"] + (i + 1) * dur})

    return {"text": text, "lines": lines, "words": words}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
