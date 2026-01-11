from fastapi import FastAPI
from fastapi.responses import JSONResponse

from plugins.tmail import router as tmail_router

app = FastAPI(title="A360 Temp Mail API")

app.include_router(tmail_router)

@app.get("/")
async def root():
    return JSONResponse(content={
        "status": "ok",
        "endpoints": [
            "/tmail/gen",
            "/tmail/cmail"
        ],
        "docs": "/docs"
    })
