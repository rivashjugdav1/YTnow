import os
import sys
import argparse
from pytube import YouTube
from pytube.exceptions import RegexMatchError, VideoUnavailable
from tqdm import tqdm


def progress_callback(stream, chunk, bytes_remaining):
    """Display download progress."""
    total_size = stream.filesize
    bytes_downloaded = total_size - bytes_remaining
    progress_bar.update(bytes_downloaded - progress_bar.n)


def download_video(url, output_path=None):
    """Download YouTube video in 1080p MP4 format."""
    if not output_path:
        output_path = os.getcwd()
    
    try:
        yt = YouTube(url)
        yt.register_on_progress_callback(progress_callback)
        
        # Get video information
        print(f"Title: {yt.title}")
        print(f"Length: {yt.length} seconds")
        print(f"Channel: {yt.author}")
        
        # Filter for mp4 streams with 1080p resolution
        streams = yt.streams.filter(file_extension='mp4', res='1080p', progressive=False)
        if not streams:
            streams = yt.streams.filter(file_extension='mp4', progressive=True)
            print("1080p MP4 not available. Downloading highest quality available.")
        
        video_stream = streams.order_by('resolution').desc().first()
        
        if not video_stream:
            print("No suitable video stream found.")
            return False
        
        print(f"Downloading: {video_stream.resolution} {video_stream.mime_type}")
        
        # Initialize progress bar
        global progress_bar
        progress_bar = tqdm(total=video_stream.filesize, unit='B', unit_scale=True, desc="Downloading")
        
        # Download the video
        out_file = video_stream.download(output_path=output_path)
        progress_bar.close()
        
        print(f"Download complete! File saved to: {out_file}")
        return True
    
    except RegexMatchError:
        print("Error: Invalid YouTube URL.")
        return False
    except VideoUnavailable:
        print("Error: The video is unavailable.")
        return False
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Download YouTube videos in MP4 format")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("-o", "--output", help="Output directory (default: current directory)")
    args = parser.parse_args()
    
    download_video(args.url, args.output)


if __name__ == "__main__":
    main() 