from flask import Flask, render_template_string, request, send_file, jsonify
import os
import tempfile
from yt_dlp import YoutubeDL

# Configure ffmpeg path
ffmpeg_path = os.path.join(os.path.dirname(__file__), 'ffmpeg-master-latest-win64-gpl', 'bin', 'ffmpeg.exe')
os.environ["PATH"] = os.path.join(os.path.dirname(__file__), 'ffmpeg-master-latest-win64-gpl', 'bin') + os.pathsep + os.environ["PATH"]

app = Flask(__name__)

from flask import Flask, render_template_string, request, send_file, jsonify, Response
import os
import tempfile
import json
from yt_dlp import YoutubeDL
from threading import Thread
import queue

app = Flask(__name__)

# Global variables for progress tracking
download_progress = {}
download_speed = {}
download_eta = {}

# Progress hook for yt-dlp
def progress_hook(d):
    video_id = d.get('info_dict', {}).get('id', 'unknown')
    if d['status'] == 'downloading':
        download_progress[video_id] = float(d.get('_percent_str', '0%').replace('%', ''))
        download_speed[video_id] = d.get('_speed_str', 'N/A')
        download_eta[video_id] = d.get('_eta_str', 'N/A')
    elif d['status'] == 'finished':
        download_progress[video_id] = 100.0

# HTML template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>YouTube Downloader</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        .container { background: #f5f5f5; padding: 20px; border-radius: 8px; }
        input[type="text"] { width: 100%; padding: 10px; margin: 10px 0; }
        button { background: #ff0000; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; margin: 5px; }
        button:hover { background: #cc0000; }
        #videoInfo { margin-top: 20px; }
        .hidden { display: none; }
        .format-options { margin: 20px 0; padding: 15px; background: #fff; border-radius: 4px; }
        .progress-bar {
            width: 100%;
            height: 20px;
            background-color: #f0f0f0;
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
        }
        .progress {
            width: 0%;
            height: 100%;
            background-color: #4CAF50;
            transition: width 0.5s ease-in-out;
        }
        .download-info {
            font-size: 14px;
            color: #666;
            margin: 5px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>YouTube Video Downloader</h1>
        <input type="text" id="urlInput" placeholder="Enter YouTube URL...">
        <button onclick="fetchInfo()">Get Video Info</button>
        <div id="videoInfo" class="hidden">
            <img id="thumbnail" style="max-width: 100%; margin: 20px 0;">
            <h2 id="title"></h2>
            <p id="channel"></p>
            <p id="duration"></p>
            
            <div class="format-options">
                <h3>Download Options</h3>
                <select id="format" onchange="updateQualityOptions()">
                    <option value="video">Video</option>
                    <option value="audio">Audio Only (MP3)</option>
                </select>
                
                <div id="videoOptions">
                    <h4>Video Quality:</h4>
                    <select id="quality">
                        <option value="2160">4K (2160p)</option>
                        <option value="1440">2K (1440p)</option>
                        <option value="1080">Full HD (1080p)</option>
                        <option value="720">HD (720p)</option>
                        <option value="480">SD (480p)</option>
                    </select>
                    
                    <h4>Frame Rate:</h4>
                    <select id="fps">
                        <option value="60">60 FPS</option>
                        <option value="30">30 FPS</option>
                    </select>
                </div>
                
                <div id="audioOptions" style="display: none;">
                    <h4>Audio Quality:</h4>
                    <select id="audioquality">
                        <option value="320">320 kbps</option>
                        <option value="256">256 kbps</option>
                        <option value="192">192 kbps</option>
                        <option value="128">128 kbps</option>
                    </select>
                </div>
            </div>
            
            <button onclick="downloadVideo()">Start Download</button>
            
            <div id="downloadProgress" class="hidden">
                <div class="progress-bar">
                    <div class="progress" id="progressBar"></div>
                </div>
                <div class="download-info">
                    <span id="progressText">0%</span>
                    <span id="speedText"></span>
                    <span id="etaText"></span>
                </div>
            </div>
        </div>
        <div id="status"></div>
    </div>
    <script>
        async function fetchInfo() {
            const url = document.getElementById('urlInput').value;
            const response = await fetch('/info?url=' + encodeURIComponent(url));
            const data = await response.json();
            
            if (data.error) {
                document.getElementById('status').textContent = data.error;
                return;
            }
            
            document.getElementById('thumbnail').src = data.thumbnail;
            document.getElementById('title').textContent = data.title;
            document.getElementById('channel').textContent = 'Channel: ' + data.channel;
            document.getElementById('duration').textContent = 'Duration: ' + data.duration + ' seconds';
            document.getElementById('videoInfo').classList.remove('hidden');
        }
        
        async function downloadVideo() {
            const url = document.getElementById('urlInput').value;
            document.getElementById('status').textContent = 'Downloading... Please wait.';
            
            try {
                const response = await fetch('/download?url=' + encodeURIComponent(url));
                const blob = await response.blob();
                
                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = downloadUrl;
                a.download = 'video.mp4';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(downloadUrl);
                
                document.getElementById('status').textContent = 'Download complete!';
            } catch (error) {
                document.getElementById('status').textContent = 'Error: ' + error.message;
            }
        }
    </script>
</body>
</html>
'''

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/info')
def get_info():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'})
    
    try:
        ydl_opts = {'quiet': True}
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({
                'title': info.get('title'),
                'channel': info.get('uploader'),
                'duration': info.get('duration'),
                'thumbnail': info.get('thumbnail')
            })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/download')
def download():
    url = request.args.get('url')
    if not url:
        return 'No URL provided', 400
    
    try:
        temp_dir = tempfile.mkdtemp()
        output_template = os.path.join(temp_dir, '%(title)s_720p60fps.%(ext)s')
        
        ydl_opts = {
            'format': 'bestvideo[height=720][fps=60][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height=720][fps=60]+bestaudio/best[height=720][fps=60]/best',
            'outtmpl': output_template,
            'quiet': True,
            'ffmpeg_location': ffmpeg_path,
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        # Find the downloaded file
        for file in os.listdir(temp_dir):
            if file.endswith('.mp4'):
                file_path = os.path.join(temp_dir, file)
                return send_file(
                    file_path,
                    as_attachment=True,
                    download_name=file
                )
        
        return 'Download failed', 500
    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    app.run(debug=True, port=8501)
