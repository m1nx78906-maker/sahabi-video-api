# ফোল্ডার: sahabi-video-api-main/xh.py
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import yt_dlp
import httpx
import urllib.parse
import re

# xHamster এর জন্য আলাদা রাউটার তৈরি করা হলো
router = APIRouter(
    prefix="/api/xh",
    tags=["xHamster API"]
)

def sanitize_filename(title: str) -> str:
    sanitized = re.sub(r'[\\/*?:"<>|]', "", title)
    return sanitized.strip() or "Sahabi_xH_Video"

# xHamster এর ইনফো API (IP Spoofing সহ)
@router.get("/info")
def get_xh_info(request: Request, url: str):
    # ইউজারের আসল আইপি বের করা
    client_ip = request.headers.get("x-forwarded-for")
    if not client_ip:
        client_ip = request.client.host
    else:
        client_ip = client_ip.split(',')[0].strip()

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'http_headers': {
            'X-Forwarded-For': client_ip, # ইউজারের আইপি পাস করা হলো
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            raw_title = info.get('title', 'Sahabi_Video')
            title = sanitize_filename(raw_title)
            thumbnail = info.get('thumbnail', '')
            
            formats_list = []
            seen_formats = set() 
            
            raw_formats = info.get('formats', [])
            raw_formats.reverse()
            
            for f in raw_formats:
                ext = f.get('ext')
                if f.get('vcodec') == 'none' and f.get('acodec') == 'none':
                    continue
                if ext not in ['mp4', 'webm']: # xHamster সাধারণত mp4 দেয়
                    continue

                height = f.get('height')
                if height:
                    if height >= 1080: quality = "1080p"
                    elif height >= 720: quality = "720p"
                    elif height >= 480: quality = "480p"
                    else: quality = f"{height}p"
                else:
                    quality = "HD/SD (Auto)" 

                unique_key = f"{quality}_Video_{ext}"
                if unique_key not in seen_formats:
                    seen_formats.add(unique_key)
                    formats_list.append({
                        "type": "Video",
                        "quality": quality,
                        "ext": ext,
                        "url": f.get('url'),
                    })

            return {
                "status": "success",
                "title": title,
                "thumbnail": thumbnail,
                "formats": formats_list
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# xHamster এর প্রক্সি ডাউনলোড API (Referer সহ)
@router.get("/download")
async def proxy_download(url: str, title: str = "Video", ext: str = "mp4"):
    target_url = urllib.parse.unquote(url)
    safe_title = sanitize_filename(title)
    filename = f"{safe_title}.{ext}"

    req_headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://xhamster.com/" # সিকিউরিটি বাইপাস
    }

    file_size = None
    async with httpx.AsyncClient(follow_redirects=True, headers=req_headers) as client:
        try:
            head_req = await client.head(target_url, timeout=10.0)
            file_size = head_req.headers.get("Content-Length")
        except: pass 

    response_headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if file_size: response_headers["Content-Length"] = str(file_size) 

    async def stream_generator():
        async with httpx.AsyncClient(follow_redirects=True, headers=req_headers, timeout=300.0) as client:
            async with client.stream("GET", target_url) as response:
                if response.status_code != 200:
                    yield b"Error fetching video."
                    return
                async for chunk in response.aiter_bytes(chunk_size=1024 * 1024 * 2): 
                    yield chunk
    
    return StreamingResponse(stream_generator(), headers=response_headers, media_type="application/octet-stream")
