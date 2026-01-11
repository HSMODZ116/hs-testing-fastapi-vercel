from fastapi import FastAPI
from fastapi.responses import JSONResponse
import os

# Import the YT router from the original project (copied into this deploy bundle)
from plugins.yt import router as yt_router

app = FastAPI(title="A360 YT API (Vercel)")

# Helpful root route
@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "A360 YT API",
        "endpoints": ["/yt/search?query=", "/yt/dl?url="]
    }

# Mount the /yt routes
app.include_router(yt_router)

# Vercel health check convenience
@app.get("/health")
async def health():
    return JSONResponse(content={"status": "healthy"})
