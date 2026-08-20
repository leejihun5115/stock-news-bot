import os
import sys
from yt_dlp import YoutubeDL

def download_youtube_media(url: str, save_dir: str = "./youtube_files"):
    """
    유튜브 URL에서 최고 화질 MP4 및 MP3 음원을 추출합니다.
    """
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    print(f"[*] 유튜브 다운로드 시작: {url}")

    video_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{save_dir}/%(title)s.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': True
    }

    audio_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{save_dir}/%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True
    }

    try:
        with YoutubeDL(video_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Unknown Title')
            description = info.get('description', '')
        
        with YoutubeDL(audio_opts) as ydl:
            ydl.download([url])
            
        print(f"[+] 다운로드 완료: {title}")
        return title, description
    except Exception as e:
        print(f"[-] 오류 발생: {e}")
        return None, None

if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else input("유튜브 URL 입력: ").strip()
    if target_url:
        download_youtube_media(target_url)
