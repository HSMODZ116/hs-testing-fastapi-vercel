import os
import re
import asyncio
import zipfile
import tempfile
import time
import uuid
import socket
import threading
import shutil
from contextlib import asynccontextmanager
from urllib.parse import urljoin, urlparse, unquote
from typing import Dict, Set, Optional
import uvloop
import aiohttp
import aiofiles
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

STORE: Dict[str, Dict] = {}
BASE_DIR = "/tmp/websource_files"
os.makedirs(BASE_DIR, exist_ok=True)

class UrlDownloader:
    def __init__(self, imgFlg=True, linkFlg=True, scriptFlg=True):
        self.soup = None
        self.imgFlg = imgFlg
        self.linkFlg = linkFlg
        self.scriptFlg = scriptFlg
        self.extensions = {
            'css': 'css', 'js': 'js', 'mjs': 'js', 'png': 'images',
            'jpg': 'images', 'jpeg': 'images', 'gif': 'images',
            'svg': 'images', 'ico': 'images', 'webp': 'images',
            'avif': 'images', 'woff': 'fonts', 'woff2': 'fonts',
            'ttf': 'fonts', 'eot': 'fonts', 'otf': 'fonts',
            'json': 'json', 'xml': 'xml', 'txt': 'txt',
            'pdf': 'documents', 'mov': 'media', 'mp4': 'media',
            'webm': 'media', 'ogg': 'media', 'mp3': 'media'
        }
        self.size_limit = 19 * 1024 * 1024
        self.semaphore = asyncio.Semaphore(25)
        self.downloaded_files: Set[str] = set()
        self.failed_urls: Set[str] = set()

    async def savePage(self, url, pagefolder='page', session=None):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'identity',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive'
            }

            async with session.get(url, timeout=20, headers=headers, allow_redirects=True) as response:
                if response.status != 200:
                    return False, f"HTTP error {response.status}", []

                content = await response.read()
                if len(content) > self.size_limit or len(content) == 0:
                    return False, "Size limit exceeded or empty content", []

                content_type = response.headers.get('content-type', '').lower()
                if not any(ct in content_type for ct in ['text/html', 'application/xhtml', 'text/xml']):
                    return False, f"Invalid content type: {content_type}", []

                try:
                    self.soup = BeautifulSoup(content, features="lxml")
                except:
                    try:
                        self.soup = BeautifulSoup(content, features="html.parser")
                    except Exception as e:
                        return False, f"Failed to parse HTML: {str(e)}", []

            os.makedirs(pagefolder, exist_ok=True)
            file_paths = []
            all_resource_urls = set()

            if self.linkFlg:
                all_resource_urls.update(self._extract_css_resources(url))
            if self.scriptFlg:
                all_resource_urls.update(self._extract_js_resources(url))
            if self.imgFlg:
                all_resource_urls.update(self._extract_image_resources(url))

            all_resource_urls.update(self._extract_other_resources(url))
            all_resource_urls.update(self._extract_inline_urls(str(self.soup), url))
            all_resource_urls.update(self._extract_meta_resources(url))
            all_resource_urls = [u for u in all_resource_urls if u and self._is_valid_url(u)]

            if all_resource_urls:
                downloaded_resources = await self._download_all_resources(list(all_resource_urls), pagefolder, session)
                file_paths.extend(downloaded_resources)

            await self._update_html_paths(url, pagefolder)

            html_path = os.path.join(pagefolder, 'index.html')
            html_content = self.soup.prettify('utf-8')
            async with aiofiles.open(html_path, 'wb') as file:
                await file.write(html_content)
            file_paths.append(html_path)

            return True, None, file_paths
        except asyncio.TimeoutError:
            return False, "Request timed out", []
        except Exception as e:
            return False, f"Failed to download: {str(e)}", []

    def _is_valid_url(self, url):
        if not url or not isinstance(url, str):
            return False
        return not url.startswith(('data:', 'blob:', 'javascript:', 'mailto:', 'tel:', '#', 'about:'))

    def _extract_css_resources(self, base_url):
        urls = set()
        if self.soup is None:
            return urls
        for link in self.soup.find_all('link', href=True):
            rel = link.get('rel', [])
            if isinstance(rel, str):
                rel = [rel]
            if 'stylesheet' in rel or link.get('type') == 'text/css':
                href = link.get('href')
                if href:
                    urls.add(urljoin(base_url, href.strip()))
        for style in self.soup.find_all('style'):
            if style.string:
                urls.update(self._extract_css_urls(style.string, base_url))
        return urls

    def _extract_js_resources(self, base_url):
        urls = set()
        if self.soup is None:
            return urls
        for script in self.soup.find_all('script', src=True):
            src = script.get('src')
            if src:
                urls.add(urljoin(base_url, src.strip()))
        return urls

    def _extract_image_resources(self, base_url):
        urls = set()
        if self.soup is None:
            return urls
        for img in self.soup.find_all('img'):
            if img.get('src'):
                urls.add(urljoin(base_url, img.get('src').strip()))
            if img.get('data-src'):
                urls.add(urljoin(base_url, img.get('data-src').strip()))
            if img.get('srcset'):
                urls.update(self._parse_srcset(img.get('srcset'), base_url))
        for source in self.soup.find_all('source'):
            if source.get('src'):
                urls.add(urljoin(base_url, source.get('src').strip()))
            if source.get('srcset'):
                urls.update(self._parse_srcset(source.get('srcset'), base_url))
        return urls

    def _extract_other_resources(self, base_url):
        urls = set()
        if self.soup is None:
            return urls
        for link in self.soup.find_all('link', href=True):
            rel = link.get('rel', [])
            if isinstance(rel, str):
                rel = [rel]
            if any(r in rel for r in ['icon', 'shortcut icon', 'apple-touch-icon', 'manifest', 'alternate', 'canonical', 'preload', 'prefetch']):
                href = link.get('href')
                if href:
                    urls.add(urljoin(base_url, href.strip()))
        for tag in self.soup.find_all(['audio', 'video', 'embed'], src=True):
            urls.add(urljoin(base_url, tag.get('src').strip()))
        for obj in self.soup.find_all('object', data=True):
            urls.add(urljoin(base_url, obj.get('data').strip()))
        return urls

    def _extract_meta_resources(self, base_url):
        urls = set()
        if self.soup is None:
            return urls
        for meta in self.soup.find_all('meta'):
            content = meta.get('content', '')
            if content and (content.startswith(('http://', 'https://', '/')) or '.' in content):
                if content.startswith('/'):
                    urls.add(urljoin(base_url, content))
                elif content.startswith(('http://', 'https://')):
                    urls.add(content)
        return urls

    def _parse_srcset(self, srcset, base_url):
        urls = set()
        if not srcset:
            return urls
        for entry in srcset.split(','):
            entry = entry.strip()
            if entry:
                parts = entry.split()
                if parts:
                    urls.add(urljoin(base_url, parts[0].strip()))
        return urls

    def _extract_css_urls(self, css_content, base_url):
        urls = set()
        url_pattern = r'url\s*\(\s*["\']?([^"\'()]+)["\']?\s*\)'
        for css_url in re.findall(url_pattern, css_content, re.IGNORECASE):
            if not css_url.startswith(('data:', 'blob:', 'javascript:')):
                urls.add(urljoin(base_url, css_url.strip()))
        import_pattern = r'@import\s+["\']([^"\']+)["\']'
        for import_url in re.findall(import_pattern, css_content, re.IGNORECASE):
            urls.add(urljoin(base_url, import_url.strip()))
        return urls

    def _extract_inline_urls(self, html_content, base_url):
        urls = set()
        style_blocks = re.findall(r'<style[^>]*>(.*?)</style>', html_content, re.DOTALL | re.IGNORECASE)
        for style_block in style_blocks:
            urls.update(self._extract_css_urls(style_block, base_url))
        script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', html_content, re.DOTALL | re.IGNORECASE)
        for script_block in script_blocks:
            js_urls = re.findall(r'["\']([^"\']*\.(js|css|png|jpg|jpeg|gif|svg|woff2?|ttf|eot|json|xml))["\']', script_block, re.IGNORECASE)
            for js_url_match in js_urls:
                js_url = js_url_match[0]
                if js_url and not js_url.startswith(('data:', 'blob:', 'javascript:')):
                    urls.add(urljoin(base_url, js_url.strip()))
        return urls

    async def _download_all_resources(self, resource_urls, pagefolder, session):
        tasks = []
        file_paths = []
        for resource_url in resource_urls:
            if resource_url not in self.downloaded_files and resource_url not in self.failed_urls:
                self.downloaded_files.add(resource_url)
                file_path = self._get_resource_path(resource_url, pagefolder)
                if file_path:
                    file_paths.append(file_path)
                    tasks.append(self._download_single_resource(resource_url, file_path, session))
        if tasks:
            batch_size = 25
            for i in range(0, len(tasks), batch_size):
                await asyncio.gather(*tasks[i:i+batch_size], return_exceptions=True)
                await asyncio.sleep(0.2)
        return file_paths

    def _get_resource_path(self, resource_url, pagefolder):
        try:
            parsed_url = urlparse(resource_url)
            path = unquote(parsed_url.path)
            if not path or path == '/':
                query = parsed_url.query
                fragment = parsed_url.fragment
                if query:
                    path = f"/query_{abs(hash(query)) % 100000}"
                elif fragment:
                    path = f"/fragment_{abs(hash(fragment)) % 100000}"
                else:
                    path = f"/resource_{abs(hash(resource_url)) % 100000}"
            path_parts = path.strip('/').split('/') if path.strip('/') else ['index']
            filename = path_parts[-1] if path_parts[-1] else 'index'
            if '.' in filename and len(filename.split('.')[-1]) <= 10:
                file_ext = filename.split('.')[-1].lower()
            else:
                file_ext = self._guess_extension_from_url(resource_url)
                if file_ext:
                    filename = f"{filename}.{file_ext}"
                else:
                    filename = f"{filename}.html"
                file_ext = file_ext or 'html'
            folder_name = self.extensions.get(file_ext, 'assets')
            if len(path_parts) > 1:
                subfolder_path = '/'.join(path_parts[:-1])
                target_folder = os.path.join(pagefolder, folder_name, subfolder_path)
            else:
                target_folder = os.path.join(pagefolder, folder_name)
            os.makedirs(target_folder, exist_ok=True)
            counter = 1
            base_filename = filename
            while True:
                full_path = os.path.join(target_folder, filename)
                if not os.path.exists(full_path):
                    break
                name, ext = os.path.splitext(base_filename)
                filename = f"{name}_{counter}{ext}"
                counter += 1
            return full_path
        except:
            return None

    def _guess_extension_from_url(self, url):
        url_lower = url.lower()
        if any(kw in url_lower for kw in ['css', 'style']):
            return 'css'
        elif any(kw in url_lower for kw in ['js', 'javascript', 'script']):
            return 'js'
        elif any(ext in url_lower for ext in ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico', 'avif']):
            for ext in ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico', 'avif']:
                if ext in url_lower:
                    return ext
        elif any(ext in url_lower for ext in ['woff2', 'woff', 'ttf', 'otf', 'eot']):
            for ext in ['woff2', 'woff', 'ttf', 'otf', 'eot']:
                if ext in url_lower:
                    return ext
        elif 'json' in url_lower or 'manifest' in url_lower:
            return 'json'
        elif 'xml' in url_lower:
            return 'xml'
        return None

    async def _download_single_resource(self, resource_url, file_path, session):
        async with self.semaphore:
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': '*/*',
                    'Accept-Encoding': 'identity',
                    'Cache-Control': 'no-cache',
                    'Referer': resource_url
                }
                async with session.get(resource_url, timeout=15, headers=headers, allow_redirects=True) as response:
                    if response.status not in [200, 206]:
                        self.failed_urls.add(resource_url)
                        return False
                    content = await response.read()
                    if len(content) > self.size_limit or len(content) == 0:
                        self.failed_urls.add(resource_url)
                        return False
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    if file_path.endswith('.css'):
                        try:
                            decoded_content = content.decode('utf-8', errors='ignore')
                            processed_content = await self._process_css_content(decoded_content, resource_url, session)
                            content = processed_content.encode('utf-8')
                        except:
                            pass
                    async with aiofiles.open(file_path, 'wb') as file:
                        await file.write(content)
                    return True
            except:
                self.failed_urls.add(resource_url)
                return False

    async def _process_css_content(self, css_content, base_url, session):
        def replace_url(match):
            url = match.group(1).strip('\'"')
            if not url.startswith(('data:', 'http://', 'https://')):
                return f'url("{urljoin(base_url, url)}")'
            return match.group(0)
        return re.sub(r'url\s*\(\s*["\']?([^"\'()]+)["\']?\s*\)', replace_url, css_content)

    async def _update_html_paths(self, base_url, pagefolder):
        if self.soup is None:
            return
        for img_tag in self.soup.find_all('img'):
            if img_tag.get('src'):
                local_path = self._get_local_path(urljoin(base_url, img_tag.get('src')), pagefolder)
                if local_path:
                    img_tag['src'] = local_path
        for link_tag in self.soup.find_all('link'):
            if link_tag.get('href'):
                local_path = self._get_local_path(urljoin(base_url, link_tag.get('href')), pagefolder)
                if local_path:
                    link_tag['href'] = local_path
        for script_tag in self.soup.find_all('script'):
            if script_tag.get('src'):
                local_path = self._get_local_path(urljoin(base_url, script_tag.get('src')), pagefolder)
                if local_path:
                    script_tag['src'] = local_path

    def _get_local_path(self, resource_url, pagefolder):
        try:
            parsed_url = urlparse(resource_url)
            path = unquote(parsed_url.path)
            if not path or path == '/':
                return None
            path_parts = path.strip('/').split('/') if path.strip('/') else ['index']
            filename = path_parts[-1] if path_parts[-1] else 'index'
            if '.' in filename and len(filename.split('.')[-1]) <= 10:
                file_ext = filename.split('.')[-1].lower()
            else:
                file_ext = self._guess_extension_from_url(resource_url) or 'html'
                filename = f"{filename}.{file_ext}"
            folder_name = self.extensions.get(file_ext, 'assets')
            if len(path_parts) > 1:
                subfolder = '/'.join(path_parts[:-1])
                return f"{folder_name}/{subfolder}/{filename}"
            else:
                return f"{folder_name}/{filename}"
        except:
            return None

def create_zip(folder_path):
    try:
        if not os.path.exists(folder_path):
            return None
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip', dir=BASE_DIR)
        temp_file.close()
        with zipfile.ZipFile(temp_file.name, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zip_file:
            file_count = 0
            total_size = 0
            for root, _, files in os.walk(folder_path):
                for file in files:
                    try:
                        file_path = os.path.join(root, file)
                        if os.path.exists(file_path):
                            file_size = os.path.getsize(file_path)
                            if total_size + file_size > 19 * 1024 * 1024:
                                continue
                            arc_name = os.path.relpath(file_path, folder_path)
                            zip_file.write(file_path, arc_name)
                            file_count += 1
                            total_size += file_size
                    except:
                        continue
            if file_count == 0:
                os.unlink(temp_file.name)
                return None
        return temp_file.name
    except:
        return None

def clean_expired_files():
    while True:
        time.sleep(30)
        now = time.time()
        dead = []
        for k, v in STORE.items():
            if now > v["exp"]:
                try:
                    if os.path.exists(v["path"]):
                        os.remove(v["path"])
                    folder = v.get("folder")
                    if folder and os.path.exists(folder):
                        shutil.rmtree(folder, ignore_errors=True)
                except:
                    pass
                dead.append(k)
        for k in dead:
            STORE.pop(k, None)

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"

@asynccontextmanager
async def lifespan(app: FastAPI):
    cleaner_thread = threading.Thread(target=clean_expired_files, daemon=True)
    cleaner_thread.start()
    print(f"[INFO] File cleaner started")
    yield
    print(f"[INFO] Shutting down API")

import httpx
import io
import base64
from datetime import datetime
app = FastAPI(title="WebSource Downloader API", lifespan=lifespan)

@app.get("/")
async def index():
    template_path = os.path.join("templates", "index.html")
    if os.path.exists(template_path):
        return FileResponse(template_path)
    raise HTTPException(status_code=404, detail="Template not found")

@app.get("/api/web")
async def download_website(request: Request, url: str = Query(..., description="Website URL to download")):
    start_time = time.time()
    
    if not url.startswith(('http://', 'https://')):
        url = f"https://{url}"
    
    fid = uuid.uuid4().hex
    pagefolder = os.path.join(BASE_DIR, f"page_{fid}")
    
    base_url = str(request.base_url).rstrip('/')
    if request.headers.get("x-forwarded-proto"):
        scheme = request.headers.get("x-forwarded-proto")
        host = request.headers.get("host", request.url.netloc)
        base_url = f"{scheme}://{host}"
    elif request.headers.get("host"):
        host = request.headers.get("host")
        scheme = "https" if "443" in host or request.url.scheme == "https" else "http"
        base_url = f"{scheme}://{host}"
    
    try:
        connector = aiohttp.TCPConnector(limit=150, limit_per_host=50, ttl_dns_cache=300)
        timeout = aiohttp.ClientTimeout(total=120, connect=20, sock_read=15)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout, auto_decompress=False) as session:
            downloader = UrlDownloader()
            success, error, file_paths = await downloader.savePage(url, pagefolder, session)
            
            if not success:
                if file_paths:
                    for fp in file_paths:
                        try:
                            os.remove(fp)
                        except:
                            pass
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": error,
                        "Developer": "Haseeb Sahil",
                        "tg_channel": "@hsmodzofc2"
                    }
                )
            
            zip_file_path = create_zip(pagefolder)
            
            for fp in file_paths:
                try:
                    os.remove(fp)
                except:
                    pass
            try:
                shutil.rmtree(pagefolder, ignore_errors=True)
            except:
                pass
            
            if not zip_file_path:
                return JSONResponse(
                    status_code=500,
                    content={
                        "success": False,
                        "error": "Failed to create zip archive",
                        "Developer": "Haseeb Sahil",
                        "tg_channel": "@hsmodzofc2"
                    }
                )
            
            expiry = time.time() + 300
            STORE[fid] = {
                "path": zip_file_path,
                "exp": expiry,
                "folder": pagefolder
            }
            
            zip_size = os.path.getsize(zip_file_path)
            domain = urlparse(url).netloc.replace('www.', '')
            time_taken = time.time() - start_time
            
            download_url = f"{base_url}/download/{fid}"
            
            print(f"[INFO] Successfully created archive for {domain} - Size: {zip_size/(1024*1024):.2f}MB - Time: {time_taken:.2f}s")
            
            return JSONResponse(content={
                "success": True,
                "file_id": fid,
                "download_url": download_url,
                "domain": domain,
                "file_size_mb": round(zip_size / (1024 * 1024), 2),
                "file_count": len(file_paths),
                "time_taken_seconds": round(time_taken, 2),
                "expires_in_seconds": 300,
                "Developer": "Haseeb Sahil",
                "tg_channel": "@hsmodzofc2"
            })
            
    except Exception as e:
        print(f"[ERROR] Failed to process {url}: {str(e)}")
        try:
            if os.path.exists(pagefolder):
                shutil.rmtree(pagefolder, ignore_errors=True)
        except:
            pass
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e),
                "Developer": "Haseeb Sahil",
                "tg_channel": "@hsmodzofc2"
            }
        )

@app.get("/download/{file_id}")
async def download_file(file_id: str):
    if file_id not in STORE:
        raise HTTPException(status_code=404, detail="File not found or expired")
    
    data = STORE[file_id]
    
    if time.time() > data["exp"]:
        try:
            os.remove(data["path"])
        except:
            pass
        STORE.pop(file_id, None)
        raise HTTPException(status_code=404, detail="File expired")
    
    if not os.path.exists(data["path"]):
        STORE.pop(file_id, None)
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        data["path"],
        media_type="application/zip",
        filename=f"website_source_{file_id}.zip"
    )

if __name__ == "__main__":
    local_ip = get_local_ip()
    
    print(f"")
    print(f"{'='*60}")
    print(f"  WebSource Downloader API - FastAPI + uvloop")
    print(f"{'='*60}")
    print(f"  Server running on:")
    print(f"  - Local:   http://127.0.0.1:3648")
    print(f"  - Network: http://{local_ip}:3648")
    print(f"  - Public:  http://0.0.0.0:3648")
    print(f"{'='*60}")
    print(f"  Dev: Haseeb Sahil")
    print(f"  Updates: @hsmodzofc2")
    print(f"{'='*60}")
    print(f"")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=3648,
        log_level="info",
        access_log=True,
        loop="uvloop"
    )

# -----------------------------
# InfinityFree Source Recovery
# (merged from second project)
# -----------------------------

class DirectSourceFetcher:
    def __init__(self):
        self.session = None
        self.cookies = {}
        
    async def get_session(self):
        if not self.session:
            self.session = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache'
                }
            )
        return self.session
        
    async def fetch_with_manual_cookies(self, url: str):
        """Manual cookie handling for InfinityFree"""
        session = await self.get_session()
        
        # First, try to get the page normally
        print(f"Attempt 1: Direct fetch {url}")
        response = await session.get(url)
        
        # Check if we got the protection page
        content = response.text
        if 'aes.js' in content and 'slowAES.decrypt' in content:
            print("Got protection page, trying manual bypass...")
            
            # Extract the encrypted data
            pattern = r'toNumbers\("([a-f0-9]+)"\)'
            matches = re.findall(pattern, content)
            
            if len(matches) >= 3:
                # These are the AES parameters
                key_hex = matches[0]  # 32 chars = 16 bytes
                iv_hex = matches[1]   # 32 chars = 16 bytes  
                ciphertext_hex = matches[2]  # 32 chars = 16 bytes
                
                print(f"Found AES parameters: key={key_hex[:16]}..., iv={iv_hex[:16]}..., cipher={ciphertext_hex[:16]}...")
                
                # Try to simulate the cookie setting
                # InfinityFree uses this cookie format: __test=decrypted_value
                # We'll try to set a dummy cookie and retry
                
                # Add the cookie manually
                session.cookies.set('__test', 'bypassed_manual_cookie')
                
                # Wait a bit
                await asyncio.sleep(2)
                
                # Try accessing with ?i=1 parameter
                if '?' in url:
                    bypass_url = url + '&i=1'
                else:
                    bypass_url = url + '?i=1'
                
                print(f"Attempt 2: Accessing {bypass_url} with manual cookie")
                response2 = await session.get(bypass_url)
                
                # Also try without protection
                no_protection_url = url.replace('https://', 'http://')
                print(f"Attempt 3: Trying HTTP version {no_protection_url}")
                response3 = await session.get(no_protection_url)
                
                # Return the most promising response
                if response2.status_code == 200 and 'aes.js' not in response2.text:
                    return response2.text, str(response2.url)
                elif response3.status_code == 200 and 'aes.js' not in response3.text:
                    return response3.text, str(response3.url)
                
        return content, str(response.url)
    
    async def try_different_paths(self, url: str):
        """Try different common InfinityFree paths"""
        parsed = urlparse(url)
        base_domain = parsed.netloc
        path = parsed.path
        
        filename = path.split('/')[-1]
        base_path = '/'.join(path.split('/')[:-1]) if '/' in path else ''
        
        # Common InfinityFree file locations
        test_urls = [
            f"https://{base_domain}{path}",
            f"https://{base_domain}{path}?i=1",
            f"https://{base_domain}{path}?nocache=1",
            f"https://{base_domain}{path}?t={int(time.time())}",
            f"http://{base_domain}{path}",
            f"https://{base_domain}/public_html{path}",
            f"https://{base_domain}/htdocs{path}",
            f"https://{base_domain}/www{path}",
            f"https://{base_domain}/~{base_domain.split('.')[0]}{path}",
            f"https://{base_domain}/files{path}",
        ]
        
        session = await self.get_session()
        
        for test_url in test_urls:
            try:
                print(f"Trying path: {test_url}")
                response = await session.get(test_url, timeout=10)
                
                if response.status_code == 200:
                    content = response.text
                    # Check if it's the actual file and not protection
                    if not ('aes.js' in content and 'slowAES.decrypt' in content):
                        print(f"Found at: {test_url}")
                        return content, test_url
                        
                await asyncio.sleep(1)
            except Exception as e:
                continue
        
        return None, None
    
    async def extract_from_source_code(self, url: str):
        """Try to extract from page source or view-source"""
        try:
            # Try view-source
            view_source_url = f"view-source:{url}"
            
            # Actually, let's try with different headers
            session = await self.get_session()
            
            # Try with different Accept headers
            headers_list = [
                {'Accept': 'text/html'},
                {'Accept': '*/*'},
                {'Accept': 'text/plain'},
                {'User-Agent': 'Googlebot/2.1 (+http://www.google.com/bot.html)'},
                {'User-Agent': 'Mozilla/5.0 (compatible; Bingbot/2.0; +http://www.bing.com/bingbot.htm)'}
            ]
            
            for headers in headers_list:
                try:
                    response = await session.get(url, headers=headers, timeout=10)
                    if response.status_code == 200:
                        content = response.text
                        if '<!DOCTYPE html>' in content and 'aes.js' not in content:
                            return content, url
                except:
                    continue
            
            return None, None
        except Exception as e:
            print(f"Source extraction error: {e}")
            return None, None
    
    async def get_original_source(self, url: str):
        """Main function to get original source"""
        print(f"\n{'='*60}")
        print(f"Trying to extract original source from: {url}")
        print(f"{'='*60}")
        
        try:
            # Method 1: Try manual cookie bypass
            print("\n[Method 1] Manual cookie bypass...")
            content1, url1 = await self.fetch_with_manual_cookies(url)
            
            if content1 and 'aes.js' not in content1:
                print("✓ Success with manual cookie bypass!")
                return content1, url1
            
            # Method 2: Try different paths
            print("\n[Method 2] Trying different InfinityFree paths...")
            content2, url2 = await self.try_different_paths(url)
            
            if content2:
                print("✓ Found via path exploration!")
                return content2, url2
            
            # Method 3: Try to extract from source
            print("\n[Method 3] Trying source code extraction...")
            content3, url3 = await self.extract_from_source_code(url)
            
            if content3:
                print("✓ Extracted from source!")
                return content3, url3
            
            # Method 4: Last resort - try direct file access patterns
            print("\n[Method 4] Last resort - direct file patterns...")
            parsed = urlparse(url)
            
            # If we're getting protection page, the actual file might be at a different location
            # InfinityFree sometimes serves from /~username/ paths
            
            # Try common username patterns
            domain_parts = parsed.netloc.split('.')
            if len(domain_parts) >= 2:
                possible_user = domain_parts[0]  # e.g., 'hs-testing-tool' from 'hs-testing-tool.gt.tc'
                
                alt_urls = [
                    f"https://{parsed.netloc}/~{possible_user}{parsed.path}",
                    f"https://{parsed.netloc}/~{possible_user}/public_html{parsed.path}",
                    f"https://{parsed.netloc}/~{possible_user}/htdocs{parsed.path}",
                    f"https://{parsed.netloc}/~{possible_user}/www{parsed.path}",
                    f"https://{parsed.netloc}/{possible_user}{parsed.path}",
                ]
                
                session = await self.get_session()
                for alt_url in alt_urls:
                    try:
                        print(f"Trying: {alt_url}")
                        response = await session.get(alt_url, timeout=10)
                        if response.status_code == 200:
                            content = response.text
                            if 'aes.js' not in content:
                                print(f"✓ Found at alternative URL: {alt_url}")
                                return content, alt_url
                    except:
                        continue
            
            print("\n✗ All methods failed!")
            return None, None
            
        except Exception as e:
            print(f"\nError during extraction: {e}")
            return None, None
        
        finally:
            # Close session
            if self.session:
                await self.session.aclose()
                self.session = None

# Create fetcher instance
fetcher = DirectSourceFetcher()

@app.get("/api/recover")
async def recover_source(url: str = Query(..., description="InfinityFree URL to recover source from")):
    """Recover original source code from InfinityFree"""
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    try:
        # Get original source
        source_code, source_url = await fetcher.get_original_source(url)
        
        if not source_code:
            raise HTTPException(status_code=404, detail="Could not recover source code. The file might be heavily protected or not accessible.")
        
        # Create a clean HTML file
        clean_html = f"""<!DOCTYPE html>
<!--
Recovered from: {url}
Source URL: {source_url}
Recovery Time: {datetime.now().isoformat()}
Original InfinityFree file recovered successfully
-->

{source_code}
"""
        
        # Return as downloadable file
        return Response(
            content=clean_html,
            media_type="text/html",
            headers={
                "Content-Disposition": "attachment; filename=recovered-original.html",
                "Content-Type": "text/html; charset=utf-8",
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Recovery failed: {str(e)}")

@app.get("/api/debug")
async def debug_url(url: str = Query(..., description="URL to debug")):
    """Debug endpoint to see what's being returned"""
    try:
        session = httpx.AsyncClient(timeout=30.0)
        response = await session.get(url, follow_redirects=True)
        
        content = response.text
        headers = dict(response.headers)
        
        # Check for InfinityFree patterns
        is_protected = 'aes.js' in content or 'slowAES.decrypt' in content
        
        return JSONResponse({
            "url": str(response.url),
            "status_code": response.status_code,
            "content_length": len(content),
            "is_infinityfree_protected": is_protected,
            "content_preview": content[:500] + "..." if len(content) > 500 else content,
            "headers": headers,
            "cookies": dict(response.cookies)
        })
        
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
