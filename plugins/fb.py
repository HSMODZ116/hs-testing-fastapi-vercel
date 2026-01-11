from fastapi import APIRouter
from fastapi.responses import JSONResponse
import requests
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urlparse, urlunparse

from utils import LOGGER

router = APIRouter(prefix="/fb", tags=["Facebook Downloader"])


def _unescape_json_str(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except Exception:
        return s.replace('\\/', '/')


def _force_mobile_host(u: str) -> str:
    """
    Convert facebook URLs to m.facebook.com safely.
    Important: avoid turning 'm.facebook.com' into 'm.m.facebook.com'
    (this happens if you do naive string replace on 'facebook.com/').
    """
    try:
        p = urlparse(u)
        host = (p.netloc or "").lower()

        # Fix bad host that can appear due to naive replaces or some share links
        if host == "m.m.facebook.com":
            host = "m.facebook.com"

        # Normalize common hosts -> mobile
        if host in {"facebook.com", "www.facebook.com", "fb.com", "www.fb.com"}:
            host = "m.facebook.com"

        # Keep fb.watch as-is (it will redirect anyway)
        if host.endswith("fb.watch"):
            return u

        return urlunparse((p.scheme or "https", host, p.path, p.params, p.query, p.fragment))
    except Exception:
        # best effort: just fix the common broken host
        return u.replace("m.m.facebook.com", "m.facebook.com")


def _extract_fb_links(html_text: str):
    """
    Try multiple strategies:
    1) playable_url_quality_hd / playable_url inside HTML/JSON blobs
    2) og:video meta tag
    """
    hd = None
    sd = None

    # JSON keys often appear escaped inside HTML
    m_hd = re.search(r'"playable_url_quality_hd"\s*:\s*"([^"]+)"', html_text)
    m_sd = re.search(r'"playable_url"\s*:\s*"([^"]+)"', html_text)

    if m_hd:
        hd = _unescape_json_str(m_hd.group(1))
    if m_sd:
        sd = _unescape_json_str(m_sd.group(1))

    # Fallback: og:video
    if not (hd or sd):
        soup = BeautifulSoup(html_text, "lxml")
        og = soup.find("meta", property="og:video")
        if og and og.get("content"):
            sd = og["content"]

    # Deduplicate
    links = []
    if hd:
        links.append({"quality": "HD", "format": "mp4", "url": hd})
    if sd and sd != hd:
        links.append({"quality": "SD", "format": "mp4", "url": sd})

    return links


@router.get("/dl")
async def fb_dl(url: str = ""):
    """
    Facebook downloader endpoint

    Example:
    /fb/dl?url=https://www.facebook.com/watch/?v=123
    /fb/dl?url=https://fb.watch/xxxx/
    /fb/dl?url=https://m.facebook.com/share/r/xxxx/
    """
    if not url:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Missing 'url' parameter",
                "api_owner": "@ISmartCoder",
                "api_updates": "t.me/abirxdhackz"
            }
        )

    # Accept various facebook hosts, including share links
    if not any(x in url for x in ["facebook.com", "fb.watch", "fb.com", "m.facebook.com", "mbasic.facebook.com", "m.m.facebook.com"]):
        return JSONResponse(
            status_code=400,
            content={
                "error": "Only Facebook URLs are supported!",
                "api_owner": "@ISmartCoder",
                "api_updates": "t.me/abirxdhackz"
            }
        )

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        # 1) Resolve redirects first (fb.watch and share links)
        r0 = requests.get(url, headers=headers, allow_redirects=True, timeout=25)
        final_url = r0.url

        # 2) Force mobile host SAFELY
        final_url = _force_mobile_host(final_url)

        # 3) Fetch page
        resp = requests.get(final_url, headers=headers, allow_redirects=True, timeout=25)
        html_text = resp.text

        # 4) Extract links
        downloads = _extract_fb_links(html_text)

        if not downloads:
            return JSONResponse(
                status_code=404,
                content={
                    "error": "No downloadable links found (video may be private/login/region-blocked).",
                    "api_owner": "@ISmartCoder",
                    "api_updates": "t.me/abirxdhackz"
                }
            )

        # Title/thumbnail (best-effort)
        soup = BeautifulSoup(html_text, "lxml")
        title = ""
        thumb = ""
        ogt = soup.find("meta", property="og:title")
        if ogt and ogt.get("content"):
            title = ogt["content"]
        ogi = soup.find("meta", property="og:image")
        if ogi and ogi.get("content"):
            thumb = ogi["content"]

        return JSONResponse(
            content={
                "status": "success",
                "title": title or "N/A",
                "thumbnail": thumb or "N/A",
                "downloads": downloads,
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
