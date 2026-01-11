from fastapi import APIRouter
from fastapi.responses import JSONResponse
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse

router = APIRouter(prefix="/fb", tags=["Facebook Downloader"])


def _is_facebook_url(u: str) -> bool:
    host = (urlparse(u).netloc or "").lower()
    return any(x in host for x in ["facebook.com", "fb.watch", "fb.com", "m.facebook.com", "mbasic.facebook.com"])


def _resolve_final_url(session: requests.Session, url: str, headers: dict) -> str:
    # Resolve redirects for share links / fb.watch
    r = session.get(url, headers=headers, allow_redirects=True, timeout=30)
    return r.url or url


def _quality_from_text(t: str) -> str:
    t = (t or "").lower()
    if "hd" in t or "high" in t:
        return "HD"
    if "sd" in t or "normal" in t or "low" in t:
        return "SD"
    if "audio" in t:
        return "AUDIO"
    return "Unknown"


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

    if not _is_facebook_url(url):
        return JSONResponse(
            status_code=400,
            content={
                "error": "Only Facebook URLs are supported!",
                "api_owner": "@ISmartCoder",
                "api_updates": "t.me/abirxdhackz"
            }
        )

    # IMPORTANT:
    # DO NOT send Accept-Encoding: br,zstd (requests may not decode zstd).
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://fdown.net/",
        "Origin": "https://fdown.net",
        "Connection": "close"
    }

    try:
        with requests.Session() as s:
            # 1) resolve FB redirects first (share/v, fb.watch etc.)
            final_fb_url = _resolve_final_url(s, url.strip(), headers)

            # 2) call fdown
            payload = {"URLz": final_fb_url}

            resp = s.post(
                "https://fdown.net/download.php",
                data=payload,
                headers=headers,
                allow_redirects=True,
                timeout=45
            )

            if resp.status_code != 200:
                return JSONResponse(
                    status_code=502,
                    content={
                        "error": "Third-party service temporarily down",
                        "api_owner": "@ISmartCoder",
                        "api_updates": "t.me/abirxdhackz"
                    }
                )

            html = resp.text or ""
            soup = BeautifulSoup(html, "html.parser")

            # Title
            title = "Facebook Video"
            title_elem = soup.find("div", class_="lib-row lib-header")
            if title_elem:
                t = title_elem.get_text(strip=True)
                if t and t.lower() != "no video title":
                    title = t

            # Thumbnail
            thumbnail = None
            img_elem = soup.find("img", class_="lib-img-show")
            if img_elem and img_elem.get("src"):
                thumb_src = img_elem["src"]
                if "no-thumbnail-fbdown.png" not in thumb_src:
                    thumbnail = thumb_src

            # 3) Extract download links
            # fdown usually puts links like:
            # <a class="btn btn-download" href="https://video.xx.fbcdn.net/....">Download in HD Quality</a>
            links = []

            # Prefer buttons
            for a in soup.select("a.btn.btn-download[href]"):
                href = a.get("href", "").strip()
                text = a.get_text(" ", strip=True)
                if href.startswith("http"):
                    links.append({"quality": _quality_from_text(text), "url": href})

            # Fallback: any anchor containing fbcdn or video_redirect
            if not links:
                for a in soup.find_all("a", href=True):
                    href = (a.get("href") or "").strip()
                    text = a.get_text(" ", strip=True)

                    if not href.startswith("http"):
                        continue

                    if ("fbcdn.net" in href) or ("video_redirect" in href) or ("download" in href.lower()):
                        links.append({"quality": _quality_from_text(text), "url": href})

            # Deduplicate
            seen = set()
            unique_links = []
            for item in links:
                u = item["url"]
                if u not in seen:
                    seen.add(u)
                    unique_links.append(item)

            if not unique_links:
                # Helpful debug hint (without leaking HTML)
                return JSONResponse(
                    status_code=404,
                    content={
                        "error": "No downloadable links found (fdown returned no links; video may be private/age/region locked, or fdown blocked your server IP).",
                        "api_owner": "@ISmartCoder",
                        "api_updates": "t.me/abirxdhackz"
                    }
                )

            return {
                "title": title,
                "thumbnail": thumbnail,
                "links": unique_links,
                "total_links": len(unique_links),
                "api_owner": "@ISmartCoder",
                "api_updates": "t.me/abirxdhackz"
            }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Server error: {str(e)}",
                "api_owner": "@ISmartCoder",
                "api_updates": "t.me/abirxdhackz"
            }
        )