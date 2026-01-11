from fastapi import FastAPI
from fastapi.responses import JSONResponse
import os, sys

# Ensure imports work on Vercel
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from plugins.fb import router as fb_router
from plugins.tik import router as tik_router
from plugins.pnt import router as pnt_router

app = FastAPI(title="A360 Social Downloader API (Fb/Tik/Pnt)")

app.include_router(fb_router, tags=["Facebook Downloader"])
app.include_router(tik_router, tags=["TikTok Downloader"])
app.include_router(pnt_router, tags=["Pinterest Downloader"])

@app.get("/")
async def root():
    return {
        "status": "ok",
        "endpoints": [

            "/fb/dl?url=",
            "/tik/dl?url=",
            "/pnt/dl?url=",
            "/docs"
        ]
    }