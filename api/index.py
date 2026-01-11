from fastapi import FastAPI
from fastapi.responses import JSONResponse

from plugins.imgai import router as imgai_router

app = FastAPI(title="A360 IMG-AI (Gemini) - Vercel Ready")
app.include_router(imgai_router)

@app.get("/")
async def root():
    return JSONResponse(content={
        "status": "ok",
        "docs": "/docs",
        "endpoints": [
            "GET /imgai/ping",
            "POST /imgai/analysis",
            "POST /imgai/ocr"
        ]
    })
