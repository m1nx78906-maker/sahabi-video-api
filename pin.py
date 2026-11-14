# sahabi-video-api-main/pin.py

from fastapi import APIRouter, Request
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

@router.get("/info")
def get_pinterest_info(url: str):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.pinterest.com/'
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            raw_title = info.get('title', 'Pinterest_Pin')
            title = sanitize_filename(raw_title)
            thumbnail = info.get('thumbnail', '')
            
            formats_list = []
            seen_formats = set()

            raw_formats = info.get('formats', [])
            raw_formats.reverse() # বেস্ট কোয়ালিটি আগে চেক হবে

            for f in raw_formats:
                ext = f.get('ext')
                protocol = f.get('protocol', '')
                video_url = f.get('url')

                # ব্রাউজারে সরাসরি চলে না এমন m3u8 বাদ দেওয়া
                if 'm3u8' in protocol or 'dash' in protocol:
                    continue

                if not video_url:
                    continue

                # পিন্টারেস্ট ভিডিওতে সাউন্ড না থাকলেও আমরা নিব (acodec চেক করে বাদ দিব না)
                vcodec = f.get('vcodec')
                if vcodec == 'none':
                    continue # অডিও-অনলি ট্র্যাক পিন্টারেস্টে দরকার নেই

                if ext not in ['mp4', 'webm', 'mov']:
                    continue

                # কোয়ালিটি ডিটেকশন
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

            # ব্যাকআপ লজিক: কোনো কারণে formats খালি থাকলে কিন্তু thumbnail/image থাকলে ইমেজ অপশন দিবে
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
        return {"status": "error", "message": str(e)}


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
