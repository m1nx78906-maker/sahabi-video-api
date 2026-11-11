from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import yt_dlp
import httpx
import urllib.parse
import re

# xh.py ফাইল থেকে xHamster এর রাউটার ইম্পোর্ট করা হলো
from xh import router as xh_router

app = FastAPI(title="Sahabi Video Downloader API")

# xHamster এর রাউটারটি মেইন অ্যাপের সাথে লিংক (Connect) করে দেওয়া হলো
app.include_router(xh_router)

# CORS Setup - ফ্রন্টএন্ড থেকে এক্সেস করার জন্য
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

def sanitize_filename(title: str) -> str:
    sanitized = re.sub(r'[\\/*?:"<>|]', "", title)
    return sanitized.strip() or "Sahabi_Video"

# ১. সাধারণ ভিডিওর (FB, TikTok, IG) ইনফো বের করার API
@app.get("/api/info")
def get_video_info(request: Request, url: str):
    # ইউটিউব আপাতত ব্লক রাখা হয়েছে
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
            
            raw_formats = info.get('formats', [])
            raw_formats.reverse() # ভালো কোয়ালিটি উপরে আনার জন্য
            
            for f in raw_formats:
                ext = f.get('ext')
                protocol = f.get('protocol', '')
                
                # লাইভ স্ট্রিম স্কিপ করা
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
                    if acodec == 'none': # সাউন্ড ছাড়া ভিডিও বাদ দেওয়া
                        continue 

                if ext not in ['mp4', 'm4a', 'mp3', 'webm']:
                    continue

                # কোয়ালিটির নাম সেট করা
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
                    elif 'watermark' in format_note: quality = "Watermarked"
                    else: quality = "HD/SD (Auto)" 

                unique_key = f"{quality}_{format_type}_{ext}"
                
                if unique_key not in seen_formats:
                    seen_formats.add(unique_key)
                    formats_list.append({
                        "type": format_type,
                        "quality": quality,
                        "ext": ext,
                        "url": f.get('url'), # Direct Link
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


# ২. সাধারণ ভিডিওর Force Download API (Proxy Server)
@app.get("/api/download")
async def proxy_download(url: str, title: str = "Sahabi_Downloader", ext: str = "mp4"):
    target_url = urllib.parse.unquote(url)
    safe_title = sanitize_filename(title)
    filename = f"{safe_title}.{ext}"

    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    file_size = None
    
    # 1st Step: ভিডিওর অরিজিনাল সাইজ (Content-Length) বের করা
    async with httpx.AsyncClient(follow_redirects=True, headers=req_headers) as client:
        try:
            head_req = await client.head(target_url, timeout=10.0)
            file_size = head_req.headers.get("Content-Length")
        except:
            pass 

    # 2nd Step: ব্রাউজারকে সাইজ বলে দেওয়া
    response_headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    if file_size:
        response_headers["Content-Length"] = str(file_size) 

    async def stream_generator():
        # timeout অনেক বাড়িয়ে দেওয়া হয়েছে যাতে বড় ভিডিও ডাউনলোড ফেল না মারে
        async with httpx.AsyncClient(follow_redirects=True, headers=req_headers, timeout=300.0) as client:
            async with client.stream("GET", target_url) as response:
                if response.status_code != 200:
                    yield b"Error fetching video"
                    return
                # Chunk size 2MB করা হয়েছে, এতে ডাউনলোড স্পিড ফাস্ট হবে
                async for chunk in response.aiter_bytes(chunk_size=1024 * 1024 * 2): 
                    yield chunk
    
    return StreamingResponse(stream_generator(), headers=response_headers, media_type="application/octet-stream")
