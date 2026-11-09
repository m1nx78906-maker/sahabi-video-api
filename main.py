from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import yt_dlp
import httpx
import urllib.parse

app = FastAPI(title="Sahabi Video Downloader API")

# CORS Setup - যাতে আপনার ফ্রন্টএন্ড (save.sahabi.top) থেকে কল করা যায়
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # লাইভ করার পর এখানে আপনার ডোমেইন বসাতে পারেন
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"message": "Welcome to Sahabi Video Downloader API. System is Running!"}

# ১. ভিডিওর ইনফো এবং লিংক বের করার API
@app.get("/api/info")
def get_video_info(url: str):
    # ইউটিউব ব্লক করার বেসিক লজিক
    if "youtube.com" in url or "youtu.be" in url:
        return {"status": "error", "message": "YouTube downloading is not supported yet."}

    # yt-dlp এর সেটিংস
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True, # আমরা ভিডিও সার্ভারে সেভ করবো না
        'format': 'bestvideo+bestaudio/best', 
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            title = info.get('title', 'Sahabi_Video')
            thumbnail = info.get('thumbnail', '')
            
            formats_list = []
            
            # সব ফরম্যাট থেকে শুধু MP4 এবং Audio ফিল্টার করা
            for f in info.get('formats', []):
                ext = f.get('ext')
                # m3u8 (Live stream format) বাদ দিচ্ছি, কারণ এগুলো সরাসরি ডাউনলোড হয় না
                if f.get('protocol') == 'm3u8_native' or f.get('protocol') == 'm3u8':
                    continue
                
                format_type = "Video"
                if f.get('vcodec') == 'none':
                    format_type = "Audio"
                    
                quality = f.get('format_note') or f.get('resolution') or "Unknown Quality"
                
                # শুধু কাজের লিংকগুলো নিবো (ভিডিও mp4 হলে বা অডিও হলে)
                if ext in ['mp4', 'm4a', 'mp3', 'webm']:
                    formats_list.append({
                        "type": format_type,
                        "quality": quality,
                        "ext": ext,
                        "url": f.get('url')
                    })
            
            # ডুপ্লিকেট রিমুভ করার একটি সিম্পল ট্রিক (অপশনাল)
            # অনেক সময় একই রেজুলেশনের ২-৩টা লিংক থাকে
            unique_formats = {f['url']: f for f in formats_list}.values()

            return {
                "status": "success",
                "title": title,
                "thumbnail": thumbnail,
                "formats": list(unique_formats)[::-1] # ভালো কোয়ালিটি উপরে রাখার জন্য রিভার্স করা
            }
            
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ২. Force Download API (ভিডিও প্লে না হয়ে সরাসরি ডাউনলোড হওয়ার জন্য)
@app.get("/api/download")
async def proxy_download(url: str, title: str = "Sahabi_Downloader", ext: str = "mp4"):
    # URL টা এনকোড করে পাঠাতে হবে ফ্রন্টএন্ড থেকে
    target_url = urllib.parse.unquote(url)
    filename = f"{title}.{ext}"

    # httpx দিয়ে অন্য সার্ভার (ফেসবুক/টিকটক) থেকে ভিডিও এনে ইউজারের ব্রাউজারে স্ট্রিম করবো
    async def stream_generator():
        async with httpx.AsyncClient(follow_redirects=True) as client:
            async with client.stream("GET", target_url) as response:
                if response.status_code != 200:
                    yield b"Error fetching video"
                    return
                async for chunk in response.aiter_bytes(chunk_size=1024 * 512): # 512KB chunks
                    yield chunk

    # Content-Disposition "attachment" মানেই ব্রাউজারকে জোর করে বলা: "প্লে করো না, ডাউনলোড করো!"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    
    return StreamingResponse(stream_generator(), headers=headers, media_type="application/octet-stream")
