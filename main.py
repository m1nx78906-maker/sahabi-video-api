from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import yt_dlp
import httpx
import urllib.parse
import re

app = FastAPI(title="Sahabi Video Downloader API")

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
    return {"message": "Welcome to Sahabi Video Downloader API. System is Running!"}

# টাইটেল থেকে স্পেশাল ক্যারেক্টার রিমুভ করার ফাংশন (ডাউনলোড ক্র্যাশ রোধ করতে)
def sanitize_filename(title: str) -> str:
    sanitized = re.sub(r'[\\/*?:"<>|]', "", title)
    return sanitized.strip() or "Sahabi_Video"

# ১. ভিডিওর ইনফো এবং লিংক বের করার API
@app.get("/api/info")
def get_video_info(url: str):
    # ইউটিউব ব্লক করা
    if "youtube.com" in url or "youtu.be" in url:
        return {"status": "error", "message": "YouTube downloading is not supported yet."}

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            raw_title = info.get('title', 'Sahabi_Video')
            title = sanitize_filename(raw_title)
            thumbnail = info.get('thumbnail', '')
            
            formats_list = []
            seen_formats = set() 
            
            # yt-dlp সাধারণত খারাপ কোয়ালিটি থেকে ভালো কোয়ালিটি সাজায়। 
            # আমরা লিস্ট উল্টে (reverse) নিচ্ছি, যাতে ভালো কোয়ালিটি আগে চেক হয়।
            raw_formats = info.get('formats', [])
            raw_formats.reverse()
            
            for f in raw_formats:
                ext = f.get('ext')
                protocol = f.get('protocol', '')
                
                # লাইভ স্ট্রিম (m3u8/dash) বাদ দেওয়া
                if 'm3u8' in protocol or 'dash' in protocol:
                    continue
                
                vcodec = f.get('vcodec')
                acodec = f.get('acodec')
                
                # যদি ভিডিও এবং অডিও কোনোটিই না থাকে
                if vcodec == 'none' and acodec == 'none':
                    continue

                # অডিও এবং ভিডিও আলাদা করার সঠিক লজিক
                if vcodec == 'none':
                    format_type = "Audio"
                else:
                    format_type = "Video"
                    # শুধুমাত্র যদি কনফার্ম হওয়া যায় যে অডিও নেই (acodec == 'none'), তবেই স্কিপ করবে।
                    # acodec যদি None (unknown) থাকে, তবে স্কিপ করবে না (এটাই আগের কোডের সমস্যা ছিল)।
                    if acodec == 'none':
                        continue 

                # শুধু কাজের এক্সটেনশন নেওয়া
                if ext not in ['mp4', 'm4a', 'mp3', 'webm']:
                    continue

                # কোয়ালিটির নাম সুন্দর করা (HD, SD, 4K ইত্যাদি)
                height = f.get('height')
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
                    quality = "Normal Quality"

                # ডুপ্লিকেট বাটন রিমুভ করার জন্য Unique Key (যাতে একই 720p দুইবার না আসে)
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
                "formats": formats_list # লিস্ট অলরেডি হাই-কোয়ালিটি থেকে লো-কোয়ালিটি সাজানো আছে
            }
            
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ২. Force Download API
@app.get("/api/download")
async def proxy_download(url: str, title: str = "Sahabi_Downloader", ext: str = "mp4"):
    target_url = urllib.parse.unquote(url)
    safe_title = sanitize_filename(title)
    filename = f"{safe_title}.{ext}"

    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    async def stream_generator():
        async with httpx.AsyncClient(follow_redirects=True, headers=req_headers, timeout=60.0) as client:
            async with client.stream("GET", target_url) as response:
                if response.status_code != 200:
                    yield b"Error fetching video"
                    return
                async for chunk in response.aiter_bytes(chunk_size=1024 * 1024): 
                    yield chunk

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    
    return StreamingResponse(stream_generator(), headers=headers, media_type="application/octet-stream")
