from fastapi import APIRouter
from fastapi.responses import JSONResponse
import requests
from bs4 import BeautifulSoup
import re
import json
from utils import LOGGER

router = APIRouter(prefix="/fb", tags=["Facebook Downloader"])

def _unescape_json_str(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except Exception:
        return s.replace('\\/', '/')

@router.get("/dl")
async def fb_downloader(url: str = ""):
    if not url:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Missing 'url' query parameter",
                "api_owner": "@ISmartCoder",
                "api_updates": "t.me/abirxdhackz"
            }
        )

    if not any(x in url for x in ["facebook.com", "fb.watch", "fb.com", "m.facebook.com"]):
        return JSONResponse(
            status_code=400,
            content={
                "error": "Only Facebook URLs are supported!",
                "api_owner": "@ISmartCoder",
                "api_updates": "t.me/abirxdhackz"
            }
        )

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        # Resolve short/redirecting links (fb.watch, etc.)
        r0 = requests.get(url, headers=headers, allow_redirects=True, timeout=20)
        final_url = r0.url

        # Prefer m.facebook.com for easier parsing (best-effort)
        if "facebook.com" in final_url and "m.facebook.com" not in final_url:
            final_url = final_url.replace("www.facebook.com", "m.facebook.com")
            final_url = final_url.replace("facebook.com/", "m.facebook.com/")

        resp = requests.get(final_url, headers=headers, allow_redirects=True, timeout=20)
        html_text = resp.text

        hd = None
        sd = None

        # Primary: embedded JSON keys
        m_hd = re.search(r'"playable_url_quality_hd"\s*:\s*"([^"]+)"', html_text)
        if m_hd:
            hd = _unescape_json_str(m_hd.group(1))

        m_sd = re.search(r'"playable_url"\s*:\s*"([^"]+)"', html_text)
        if m_sd:
            sd = _unescape_json_str(m_sd.group(1))

        # Fallback: OG meta
        soup = BeautifulSoup(html_text, "lxml")
        if not (hd or sd):
            og = soup.find("meta", property="og:video") or soup.find("meta", property="og:video:url")
            if og and og.get("content"):
                sd = og["content"]

        links = []
        if hd:
            links.append({"quality": "HD", "format": "mp4", "url": hd})
        if sd and sd != hd:
            links.append({"quality": "SD", "format": "mp4", "url": sd})

        if not links:
            return JSONResponse(
                status_code=404,
                content={
                    "error": "No downloadable links found",
                    "api_owner": "@ISmartCoder",
                    "api_updates": "t.me/abirxdhackz"
                }
            )

        # Title & thumbnail (best effort)
        title = (soup.find("meta", property="og:title") or {}).get("content") if soup else None
        thumb = (soup.find("meta", property="og:image") or {}).get("content") if soup else None

        return JSONResponse(
            content={
                "status": "success",
                "title": title or "N/A",
                "thumbnail": thumb or "N/A",
                "downloads": links,
                "api_owner": "@ISmartCoder",
                "api_updates": "t.me/abirxdhackz"
            }
        )

    except Exception as e:
        LOGGER.error(f"FB downloader error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Server error: {str(e)}",
                "api_owner": "@ISmartCoder",
                "api_updates": "t.me/abirxdhackz"
            }
        )
