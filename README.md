# YouTube Video Downloader

A web application that allows users to download YouTube videos in high quality (720p 60fps).

## Features

- Simple, user-friendly web interface
- High-quality video downloads (1080p 60fps)
- Download videos directly to mp3 format(Perfect for music)
- Video information preview with thumbnails
- Progress tracking
- Direct browser downloads
- Accessible from any device with a web browser


## Note

This app is for educational purposes only. Please respect YouTube's terms of service and copyright laws when downloading videos.

## Requirements

- Python 3.6+
- Required Python packages (install with `pip install -r requirements.txt`):
  - pytube (for YouTube video downloading)
  - tqdm (for CLI progress bar)
  - tkinter (included with Python for GUI version)

## Installation

1. Clone or download this repository
2. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

## Usage

### Command Line Interface

```
python youtube_downloader.py https://www.youtube.com/watch?v=VIDEO_ID
```

Optional arguments:
- `-o, --output` - Specify the output directory (default: current directory)

Example:
```
python youtube_downloader.py https://www.youtube.com/watch?v=dQw4w9WgXcQ -o C:/Downloads
```

### GUI Application

Run the GUI version:
```
python youtube_downloader_gui.py
```

1. Enter the YouTube video URL
2. Choose the output directory (default is your Downloads folder)
3. Click "Fetch Video Info" to verify the video
4. Click "Download Video" to begin downloading

## Notes

- The downloader attempts to get 1080p MP4 videos first
- If 1080p is not available, it defaults to the highest available quality
- YouTube videos with 1080p+ resolution often have separate audio and video streams, so the download combines them

## Limitations

- Only supports YouTube videos (not playlists or channels)
- Some videos might have restrictions or be unavailable for download
- DRM-protected content cannot be downloaded

## License

This project is for educational purposes only. Be aware that downloading videos may violate YouTube's Terms of Service. Always respect copyright and use responsibly. 
