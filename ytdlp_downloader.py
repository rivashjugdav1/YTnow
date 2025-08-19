import os
import sys
import argparse
from yt_dlp import YoutubeDL

def download_video(url, output_path=None):
    """Download YouTube video in 720p 60fps MP4 format."""
    if not output_path:
        output_path = os.getcwd()
    
    # Output template
    output_template = os.path.join(output_path, '%(title)s_720p60fps.%(ext)s')
    
    # yt-dlp options for 720p60fps, merging if needed
    ydl_opts = {
        'format': 'bestvideo[height=720][fps=60][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height=720][fps=60]+bestaudio/best[height=720][fps=60]/best',
        'outtmpl': output_template,
        'progress_hooks': [progress_hook],
        'quiet': False,
        'no_warnings': False,
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            print(f"Title: {info.get('title')}")
            print(f"Duration: {info.get('duration')} seconds")
            print(f"Channel: {info.get('uploader')}")
            print("\nDownloading in 720p 60fps...")
            ydl.download([url])
            print("\nDownload complete!")
        return True
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return False

def progress_hook(d):
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', 'N/A')
        speed = d.get('_speed_str', 'N/A')
        eta = d.get('_eta_str', 'N/A')
        print(f"\rDownloading... {percent} at {speed}, ETA: {eta}", end='', flush=True)
    elif d['status'] == 'finished':
        print("\nDownload finished, processing with FFmpeg...")

def main():
    parser = argparse.ArgumentParser(description="Download YouTube videos in 720p 60fps MP4 format using yt-dlp")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("-o", "--output", help="Output directory (default: current directory)")
    args = parser.parse_args()
    download_video(args.url, args.output)

if __name__ == "__main__":
    main() 