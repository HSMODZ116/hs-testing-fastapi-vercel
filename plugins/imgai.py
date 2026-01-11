from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import os
import httpx

from utils import LOGGER

router = APIRouter(prefix="/imgai", tags=["Image AI (Gemini)"])

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
# Gemini endpoint for multimodal text generation
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

class ImageAIRequest(BaseModel):
    code: str = Field(..., description="Base64 image data (no data: prefix)")
    mimeType: str = Field("image/jpeg", description="image/jpeg, image/png, image/webp")
    prompt: str | None = Field(None, description="Instruction for the model")

def _needs_key():
    return not GEMINI_API_KEY

async def _call_gemini(prompt: str, b64: str, mime: str):
    if _needs_key():
        return None, "Missing GEMINI_API_KEY (set it in Vercel Environment Variables)."

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inlineData": {"mimeType": mime, "data": b64}}
                ]
            }
        ]
    }

    params = {"key": GEMINI_API_KEY}

    timeout = httpx.Timeout(45.0, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(GEMINI_URL, params=params, json=payload)
        if r.status_code != 200:
            # Don't leak key; return helpful message
            return None, f"Gemini API error: {r.status_code} - {r.text[:400]}"
        data = r.json()

    # Extract text from candidates
    try:
        candidates = data.get("candidates", [])
        if not candidates:
            return None, "No candidates returned."
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join([p.get("text", "") for p in parts if isinstance(p, dict)])
        text = text.strip()
        return text if text else None, "Empty response text."
    except Exception as e:
        return None, f"Failed to parse Gemini response: {e}"

@router.get("/ping")
async def ping():
    return {"status": "ok", "has_key": bool(GEMINI_API_KEY)}

@router.post("/analysis")
async def analysis(req: ImageAIRequest):
    prompt = (req.prompt or "").strip() or "Describe this image in detail. Include objects, text, and any notable elements."
    try:
        result, err = await _call_gemini(prompt, req.code.strip(), req.mimeType.strip())
        if result is None:
            return JSONResponse(
                status_code=400 if "Missing GEMINI_API_KEY" in (err or "") else 502,
                content={
                    "success": False,
                    "error": err,
                    "api_owner": "@ISmartCoder",
                    "api_updates": "t.me/abirxdhackz"
                }
            )
        return {
            "success": True,
            "prompt": prompt,
            "result": result,
            "api_owner": "@ISmartCoder",
            "api_updates": "t.me/abirxdhackz"
        }
    except Exception as e:
        LOGGER.error(f"imgai/analysis error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Server error: {str(e)}",
                "api_owner": "@ISmartCoder",
                "api_updates": "t.me/abirxdhackz"
            }
        )

@router.post("/ocr")
async def ocr(req: ImageAIRequest):
    # Strong OCR prompt
    prompt = (req.prompt or "").strip() or (
        "Extract all readable text from this image. "
        "Return ONLY the text, preserving line breaks. "
        "If there is no text, return 'NO_TEXT_FOUND'."
    )
    try:
        result, err = await _call_gemini(prompt, req.code.strip(), req.mimeType.strip())
        if result is None:
            return JSONResponse(
                status_code=400 if "Missing GEMINI_API_KEY" in (err or "") else 502,
                content={
                    "success": False,
                    "error": err,
                    "api_owner": "@ISmartCoder",
                    "api_updates": "t.me/abirxdhackz"
                }
            )
        return {
            "success": True,
            "result": result,
            "api_owner": "@ISmartCoder",
            "api_updates": "t.me/abirxdhackz"
        }
    except Exception as e:
        LOGGER.error(f"imgai/ocr error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Server error: {str(e)}",
                "api_owner": "@ISmartCoder",
                "api_updates": "t.me/abirxdhackz"
            }
        )
