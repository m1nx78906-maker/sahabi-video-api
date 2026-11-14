# sahabi-video-api-main/pin.py

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import yt_dlp
import httpx
import urllib.parse
import re

router = APIRouter(
    prefix="/api/pin",
    tags=["Pinterest API"]
)

def sanitize_filename(title: str) -> str:
    sanitized = re.sub(r'[\\/*?:"<>|]', "", title)
    return sanitized.strip() or "Pinterest_Media"

# শর্ট লিংক (pin.it) কে আসল পিন লিংকে কনভার্ট করার ফাংশন
async def expand_pinterest_url(url: str) -> str:
    if "pin.it" in url:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                resp = await client.head(url)
                return str(resp.url)
        except Exception:
            return url
    return url

@router.get("/info")
async def get_pinterest_info(url: str):
    # ১. শর্ট লিংক ফিক্স
    resolved_url = await expand_pinterest_url(url)

    # ২. মোবাইল ব্রাউজারের হেডার যাতে Pinterest লগইন ওয়াল না দেয়
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.pinterest.com/'
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(resolved_url, download=False)
            
            raw_title = info.get('title', 'Pinterest_Pin')
            title = sanitize_filename(raw_title)
            thumbnail = info.get('thumbnail', '')
            
            formats_list = []
            seen_formats = set()

            raw_formats = info.get('formats', [])
            raw_formats.reverse()

            for f in raw_formats:
                ext = f.get('ext')
                protocol = f.get('protocol', '')
                video_url = f.get('url')

                if 'm3u8' in protocol or 'dash' in protocol:
                    continue

                if not video_url:
                    continue

                vcodec = f.get('vcodec')
                if vcodec == 'none':
                    continue

                if ext not in ['mp4', 'webm', 'mov']:
                    continue

                height = f.get('height')
                if height:
                    if height >= 1080: quality = "1080p (FHD)"
                    elif height >= 720: quality = "720p (HD)"
                    elif height >= 480: quality = "480p (SD)"
                    else: quality = f"{height}p"
                else:
                    quality = "HD Video"

                unique_key = f"{quality}_{ext}"
                if unique_key not in seen_formats:
                    seen_formats.add(unique_key)
                    formats_list.append({
                        "type": "Video",
                        "quality": quality,
                        "ext": ext,
                        "url": video_url,
                        "size_bytes": f.get('filesize') or f.get('filesize_approx')
                    })

            # যদি কোনো ভিডিও না থাকে, তাহলে অরিজিনাল সাইজের ছবি (Image Pin) রিটার্ন করবে
            if not formats_list:
                img_url = info.get('url') or thumbnail
                if img_url:
                    formats_list.append({
                        "type": "Image",
                        "quality": "Original HD Image",
                        "ext": "jpg",
                        "url": img_url,
                        "size_bytes": None
                    })

            return {
                "status": "success",
                "title": title,
                "thumbnail": thumbnail,
                "formats": formats_list
            }

    except Exception as e:
        # Pinterest নিজস্ব ডিরেক্ট ইমেজ স্ক্র্যাপিং ফলব্যাক
        return {"status": "error", "message": f"Pinterest Error: {str(e)}"}


@router.get("/download")
async def proxy_download(url: str, title: str = "Pinterest_Media", ext: str = "mp4"):
    target_url = urllib.parse.unquote(url)
    safe_title = sanitize_filename(title)
    filename = f"{safe_title}.{ext}"

    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.pinterest.com/"
    }

    file_size = None
    async with httpx.AsyncClient(follow_redirects=True, headers=req_headers) as client:
        try:
            head_req = await client.head(target_url, timeout=10.0)
            file_size = head_req.headers.get("Content-Length")
        except:
            pass

    response_headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    if file_size:
        response_headers["Content-Length"] = str(file_size)

    async def stream_generator():
        async with httpx.AsyncClient(follow_redirects=True, headers=req_headers, timeout=300.0) as client:
            async with client.stream("GET", target_url) as response:
                if response.status_code != 200:
                    yield b"Error fetching Pinterest media"
                    return
                async for chunk in response.aiter_bytes(chunk_size=1024 * 1024 * 2):
                    yield chunk

    return StreamingResponse(stream_generator(), headers=response_headers, media_type="application/octet-stream")
