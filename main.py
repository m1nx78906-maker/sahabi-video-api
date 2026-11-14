# sahabi-video-api-main/main.py

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import yt_dlp
import httpx
import urllib.parse
import re

# xh.py থেকে xHamster রাউটার লিঙ্ক করা
from xh import router as xh_router

app = FastAPI(title="Sahabi Video Downloader API")

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
    return {"message": "Sahabi Video Downloader API is Running Smoothly!"}

def sanitize_filename(title: str) -> str:
    sanitized = re.sub(r'[\\/*?:"<>|]', "", title)
    return sanitized.strip() or "Sahabi_Video"

# 🔥 স্পেশাল টিকটক হ্যান্ডলার (No Watermark Engine)
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
                
                # 1. No Watermark HD Video
                video_url = data.get("play")
                if video_url:
                    formats.append({
                        "type": "Video",
                        "quality": "HD (No Watermark)",
                        "ext": "mp4",
                        "url": video_url
                    })
                
                # 2. Audio MP3
                music_url = data.get("music")
                if music_url:
                    formats.append({
                        "type": "Audio",
                        "quality": "Audio MP3",
                        "ext": "mp3",
                        "url": music_url
                    })
                    
                return {
                    "status": "success",
                    "title": title,
                    "thumbnail": thumbnail,
                    "formats": formats
                }
    except Exception:
        pass
    return None


# ১. ভিডিওর ইনফো বের করার API
@app.get("/api/info")
async def get_video_info(request: Request, url: str):
    # ইউটিউব ব্লক
    if "youtube.com" in url or "youtu.be" in url:
        return {"status": "error", "message": "YouTube downloading is not supported yet."}

    # 🔥 টিকটক হলে সরাসরি হাই-স্পিড ইঞ্জিনে পাঠাবে
    if "tiktok.com" in url or "douyin.com" in url:
        tt_result = await fetch_tiktok_direct(url)
        if tt_result:
            return tt_result

    # অন্যান্য প্ল্যাটফর্মের জন্য yt-dlp
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
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
                protocol = f.get('protocol', '')
                
                if 'm3u8' in protocol or 'dash' in protocol:
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
                    if height >= 2160: quality = "4K"
                    elif height >= 1080: quality = "1080p (FHD)"
                    elif height >= 720: quality = "720p (HD)"
                    elif height >= 480: quality = "480p (SD)"
                    elif height >= 360: quality = "360p"
                    else: quality = f"{height}p"
                else:
                    if '1080' in format_note or 'hd1080' in format_id: quality = "1080p (FHD)"
                    elif '720' in format_note or 'hd720' in format_id or 'hd' in format_note: quality = "720p (HD)"
                    elif 'sd' in format_note or 'sd' in format_id: quality = "480p (SD)"
                    else: quality = "HD/SD (Auto)" 

                unique_key = f"{quality}_{format_type}_{ext}"
                
                if unique_key not in seen_formats:
                    seen_formats.add(unique_key)
                    formats_list.append({
                        "type": format_type,
                        "quality": quality,
                        "ext": ext,
                        "url": f.get('url'),
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


# ২. Force Download API (Server Proxy)
@app.get("/api/download")
async def proxy_download(url: str, title: str = "Sahabi_Downloader", ext: str = "mp4"):
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
                    yield b"Error fetching video"
                    return
                async for chunk in response.aiter_bytes(chunk_size=1024 * 1024 * 2): 
                    yield chunk
    
    return StreamingResponse(stream_generator(), headers=response_headers, media_type="application/octet-stream")
