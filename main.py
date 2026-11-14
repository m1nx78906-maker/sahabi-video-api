# sahabi-video-api-main/main.py

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import yt_dlp
import httpx
import urllib.parse
import re

# xHamster রাউটার লিংক করা
try:
    from xh import router as xh_router
except Exception:
    xh_router = None

app = FastAPI(title="Sahabi Video Downloader API")

if xh_router:
    app.include_router(xh_router)

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"message": "Sahabi Video Downloader API is Running!"}

def sanitize_filename(title: str) -> str:
    sanitized = re.sub(r'[\\/*?:"<>|]', "", title)
    return sanitized.strip() or "Sahabi_Video"

# শর্ট লিংক (যেমন pin.it) রিডাইরেক্ট করে আসল লিংক পাওয়ার ফাংশন
async def expand_url(url: str) -> str:
    if "pin.it" in url or "vm.tiktok.com" in url:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                resp = await client.head(url)
                return str(resp.url)
        except Exception:
            return url
    return url

# টিকটক হ্যান্ডলার (No Watermark)
async def fetch_tiktok_direct(url: str):
    try:
        api_url = "https://www.tikwm.com/api/"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(api_url, data={"url": url})
            res_data = resp.json()
            if res_data.get("code") == 0:
                data = res_data["data"]
                title = sanitize_filename(data.get("title", "TikTok_Video"))
                thumbnail = data.get("cover", "")
                formats = []
                if data.get("play"):
                    formats.append({"type": "Video", "quality": "HD (No Watermark)", "ext": "mp4", "url": data.get("play")})
                if data.get("music"):
                    formats.append({"type": "Audio", "quality": "Audio MP3", "ext": "mp3", "url": data.get("music")})
                return {"status": "success", "title": title, "thumbnail": thumbnail, "formats": formats}
    except Exception:
        pass
    return None

# Pinterest স্পেশাল ভিডিও এক্সট্রাক্টর
def extract_pinterest_formats(info: dict, thumbnail: str):
    formats_list = []
    seen = set()

    for f in info.get('formats', []):
        url = f.get('url', '')
        if not url:
            continue
        ext = f.get('ext')
        height = f.get('height') or 720
        quality = f"{height}p (HD)" if height >= 720 else f"{height}p"

        # প্রগ্রেসিভ সরাসরি MP4 ভিডিও
        if ext in ['mp4', 'mov', 'webm'] and 'm3u8' not in url and url not in seen:
            seen.add(url)
            formats_list.append({
                "type": "Video",
                "quality": quality,
                "ext": "mp4",
                "url": url,
                "size_bytes": f.get('filesize') or f.get('filesize_approx')
            })

    # যদি MP4 না পাওয়া যায়, তবে HLS/m3u8 এর সেরা স্ট্রিমটি নিব
    if not formats_list:
        for f in info.get('formats', []):
            url = f.get('url', '')
            if ('m3u8' in url or f.get('protocol') in ['m3u8', 'm3u8_native']) and url not in seen:
                seen.add(url)
                height = f.get('height') or 720
                quality = f"{height}p (HD Stream)"
                formats_list.append({
                    "type": "Video",
                    "quality": quality,
                    "ext": "mp4",
                    "url": url,
                    "size_bytes": None
                })
                break

    # যদি ভিডিও একদমই না থাকে তবে অরিজিনাল ছবি
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

    return formats_list


# মেইন ইনফো API
@app.get("/api/info")
async def get_video_info(request: Request, url: str):
    if "youtube.com" in url or "youtu.be" in url:
        return {"status": "error", "message": "YouTube downloading is not supported yet."}

    # ১. শর্ট লিংক এক্সপ্যান্ড
    resolved_url = await expand_url(url)

    # ২. টিকটক হলে ফাস্ট ইঞ্জিন
    if "tiktok.com" in resolved_url or "douyin.com" in resolved_url:
        tt_result = await fetch_tiktok_direct(resolved_url)
        if tt_result:
            return tt_result

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.pinterest.com/' if 'pinterest' in resolved_url or 'pin.it' in url else 'https://www.google.com/'
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(resolved_url, download=False)
            raw_title = info.get('title', 'Sahabi_Media')
            title = sanitize_filename(raw_title)
            thumbnail = info.get('thumbnail', '')

            # পিন্টারেস্টের জন্য স্পেশাল প্রসেসিং
            if "pinterest.com" in resolved_url or "pinimg.com" in resolved_url or "pin.it" in url:
                formats_list = extract_pinterest_formats(info, thumbnail)
                return {
                    "status": "success",
                    "title": title,
                    "thumbnail": thumbnail,
                    "formats": formats_list
                }

            # ফেসবুক, টুইটার, ইত্যাদির জন্য সাধারণ প্রসেসিং
            formats_list = []
            seen_formats = set()
            raw_formats = info.get('formats', [])
            raw_formats.reverse()

            for f in raw_formats:
                ext = f.get('ext')
                protocol = f.get('protocol', '')
                video_url = f.get('url')

                if 'm3u8' in protocol or 'dash' in protocol or not video_url:
                    continue

                vcodec = f.get('vcodec')
                acodec = f.get('acodec')

                if vcodec == 'none' and acodec == 'none':
                    continue

                if vcodec == 'none':
                    format_type = "Audio"
                else:
                    format_type = "Video"
                    if acodec == 'none':
                        continue

                if ext not in ['mp4', 'm4a', 'mp3', 'webm']:
                    continue

                height = f.get('height')
                format_note = str(f.get('format_note', '')).lower()
                format_id = str(f.get('format_id', '')).lower()

                if format_type == "Audio":
                    quality = "Audio"
                elif height:
                    if height >= 1080: quality = "1080p (FHD)"
                    elif height >= 720: quality = "720p (HD)"
                    elif height >= 480: quality = "480p (SD)"
                    elif height >= 360: quality = "360p"
                    else: quality = f"{height}p"
                else:
                    if '1080' in format_note or 'hd1080' in format_id: quality = "1080p (FHD)"
                    elif '720' in format_note or 'hd720' in format_id: quality = "720p (HD)"
                    else: quality = "HD/SD (Auto)"

                unique_key = f"{quality}_{format_type}_{ext}"
                if unique_key not in seen_formats:
                    seen_formats.add(unique_key)
                    formats_list.append({
                        "type": format_type,
                        "quality": quality,
                        "ext": ext,
                        "url": video_url,
                        "size_bytes": f.get('filesize') or f.get('filesize_approx')
                    })

            return {
                "status": "success",
                "title": title,
                "thumbnail": thumbnail,
                "formats": formats_list
            }

    except Exception as e:
        return {"status": "error", "message": str(e)}


# ডাউনলোড প্রক্সি
@app.get("/api/download")
async def proxy_download(url: str, title: str = "Sahabi_Media", ext: str = "mp4"):
    target_url = urllib.parse.unquote(url)
    safe_title = sanitize_filename(title)
    filename = f"{safe_title}.{ext}"

    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    file_size = None
    async with httpx.AsyncClient(follow_redirects=True, headers=req_headers) as client:
        try:
            head_req = await client.head(target_url, timeout=10.0)
            file_size = head_req.headers.get("Content-Length")
        except Exception:
            pass

    response_headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if file_size:
        response_headers["Content-Length"] = str(file_size)

    async def stream_generator():
        async with httpx.AsyncClient(follow_redirects=True, headers=req_headers, timeout=300.0) as client:
            async with client.stream("GET", target_url) as response:
                if response.status_code != 200:
                    yield b"Error fetching video"
                    return
                async for chunk in response.aiter_bytes(chunk_size=1024 * 1024 * 2):
                    yield chunk

    return StreamingResponse(stream_generator(), headers=response_headers, media_type="application/octet-stream")
