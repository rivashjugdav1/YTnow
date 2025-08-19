from flask import Flask, render_template_string, request, send_file, jsonify, Response, redirect, url_for, session
import os
import tempfile
import json
import time
from collections import deque
from yt_dlp import YoutubeDL
from downloader import apply_common_ydl_hardening
from threading import Thread
import queue
import sqlite3
from flask_session import Session
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
import google.auth.transport.requests
import pathlib

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret')
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

# OAuth2 Configuration
CLIENT_SECRETS_FILE = os.path.join(os.path.dirname(__file__), 
    'client_secret_404561069273-v3q9cju9t3lhn69m9jt8igbg9dvc5ntl.apps.googleusercontent.com.json')
SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/youtube.force-ssl'
]

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # TODO: Remove this in production

def credentials_to_dict(credentials):
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

# Global variables for progress tracking
download_progress = {}
download_speed = {}
download_eta = {}

# API keys and SQLite rate limiting
VALID_API_KEYS = [k.strip() for k in os.environ.get('API_KEYS', '').split(',') if k.strip()]
RATE_LIMIT_MAX = int(os.environ.get('RATE_LIMIT_MAX', '3'))
RATE_LIMIT_WINDOW_SEC = int(os.environ.get('RATE_LIMIT_WINDOW_SEC', str(10 * 60)))
RATE_LIMIT_COOLDOWN_SEC = int(os.environ.get('RATE_LIMIT_COOLDOWN_SEC', '30'))
DB_PATH = os.path.join(os.path.dirname(__file__), 'rate_limit.sqlite')

def _db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_db():
    conn = _db_conn()
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS request_log (ip TEXT NOT NULL, ts INTEGER NOT NULL)')
        conn.execute('''CREATE TABLE IF NOT EXISTS user_auth (
            user_id TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            name TEXT,
            credentials TEXT
        )''')
        conn.commit()
    finally:
        conn.close()

@app.route('/login')
def login():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=url_for('oauth2callback', _external=True)
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    state = session.get('state')
    if not state:
        return redirect(url_for('index'))

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri=url_for('oauth2callback', _external=True)
    )
    
    authorization_response = request.url
    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials

    try:
        request_session = google.auth.transport.requests.Request()
        id_info = id_token.verify_oauth2_token(
            credentials.id_token, request_session, credentials.client_id)
        
        conn = _db_conn()
        try:
            conn.execute(
                'INSERT OR REPLACE INTO user_auth (user_id, email, name, credentials) VALUES (?, ?, ?, ?)',
                (id_info['sub'], id_info['email'], id_info.get('name'), json.dumps(credentials_to_dict(credentials)))
            )
            conn.commit()
            
            session['user_id'] = id_info['sub']
            session['email'] = id_info['email']
            session['name'] = id_info.get('name')
            session['credentials'] = credentials_to_dict(credentials)
        finally:
            conn.close()
            
    except Exception as e:
        print(f"Error in OAuth callback: {str(e)}")
        return redirect(url_for('index'))

    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

def is_rate_limited(ip: str) -> tuple[bool, str]:
    now = int(time.time())
    window_start = now - RATE_LIMIT_WINDOW_SEC
    conn = _db_conn()
    try:
        conn.execute('DELETE FROM request_log WHERE ts < ?', (window_start - 3600,))
        conn.commit()
        rows = [r[0] for r in conn.execute('SELECT ts FROM request_log WHERE ip = ? AND ts >= ? ORDER BY ts ASC', (ip, window_start)).fetchall()]
        if rows:
            if now - rows[-1] < RATE_LIMIT_COOLDOWN_SEC:
                wait = RATE_LIMIT_COOLDOWN_SEC - (now - rows[-1])
                return True, f"Too many requests. Please wait {wait}s before starting another download."
        if len(rows) >= RATE_LIMIT_MAX:
            return True, "Rate limit exceeded. Try again later."
        conn.execute('INSERT INTO request_log (ip, ts) VALUES (?, ?)', (ip, now))
        conn.commit()
        return False, ''
    finally:
        conn.close()

# Progress hook for yt-dlp
def progress_hook(d):
    video_id = d.get('info_dict', {}).get('id', 'unknown')
    if d['status'] == 'downloading':
        try:
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            if total > 0:
                percentage = (downloaded / total) * 100
            else:
                percentage = 0
            
            download_progress[video_id] = percentage
            download_speed[video_id] = d.get('speed_str', d.get('_speed_str', 'N/A'))
            download_eta[video_id] = d.get('eta_str', d.get('_eta_str', 'N/A'))
            print(f"Download Progress: {percentage:.1f}% Speed: {download_speed[video_id]} ETA: {download_eta[video_id]}")
        except Exception as e:
            print(f"Error in progress_hook: {str(e)}")
    elif d['status'] == 'finished':
        download_progress[video_id] = 100.0
        print("Download finished, now converting...")

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
        .user-info { 
            float: right;
            text-align: right;
            margin-bottom: 20px;
        }
        .login-btn {
            background: #4285f4;
        }
        .login-btn:hover {
            background: #357abd;
        }
        .logout-btn {
            background: #757575;
        }
        .logout-btn:hover {
            background: #606060;
        }
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
        .download-info { font-size: 14px; color: #666; margin: 5px 0; }
        select {
            padding: 5px;
            margin: 5px 0;
            border-radius: 4px;
            border: 1px solid #ddd;
        }
        .cookies { margin-top: 10px; }
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
                <div class="cookies">
                    <label>API Key (if required)</label>
                    <input type="text" id="apiKey" placeholder="Enter API key" />
                </div>
                <div class="cookies">
                    <button type="button" onclick="googleLogin()">Sign in with Google for age-restricted videos</button>
                </div>
            </div>
            
            <button onclick="downloadVideo()">Start Download</button>
            
            <div id="downloadProgress" class="hidden">
                <div class="progress-bar">
                    <div class="progress" id="progressBar"></div>
                </div>
                <div class="download-info" id="progressInfo">0% - --:-- remaining</div>
            </div>
        </div>
        <div id="status"></div>
    </div>
    <script>
        function googleLogin() {
            window.location.href = '/auth/login';
        }

        function updateQualityOptions() {
            const format = document.getElementById('format').value;
            document.getElementById('videoOptions').style.display = format === 'video' ? 'block' : 'none';
            document.getElementById('audioOptions').style.display = format === 'audio' ? 'block' : 'none';
        }
        
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
            document.getElementById('duration').textContent = 'Duration: ' + Math.floor(data.duration / 60) + ':' + (data.duration % 60).toString().padStart(2, '0');
            document.getElementById('videoInfo').classList.remove('hidden');
        }
        
        let progressInterval;
        
        async function downloadVideo() {
            const url = document.getElementById('urlInput').value;
            const format = document.getElementById('format').value;
            const quality = format === 'video' ? document.getElementById('quality').value : null;
            const fps = format === 'video' ? document.getElementById('fps').value : null;
            const audioQuality = format === 'audio' ? document.getElementById('audioquality').value : null;
            const apiKeyEl = document.getElementById('apiKey');
            
            document.getElementById('downloadProgress').classList.remove('hidden');
            document.getElementById('status').textContent = 'Starting download...';
            
            // Start progress monitoring
            progressInterval = setInterval(updateProgress, 1000);
            
            try {
                const formData = new FormData();
                formData.append('url', url);
                formData.append('format', format);
                if (quality) formData.append('quality', quality);
                if (fps) formData.append('fps', fps);
                if (audioQuality) formData.append('audioQuality', audioQuality);
                const apiKeyEl = document.getElementById('apiKey');
                if (apiKeyEl && apiKeyEl.value) {
                    formData.append('apiKey', apiKeyEl.value);
                }

                const response = await fetch('/download', { method: 'POST', body: formData });
                if (!response.ok) {
                    const text = await response.text();
                    throw new Error(text || 'Download failed');
                }
                
                const blob = await response.blob();
                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = downloadUrl;
                a.download = format === 'audio' ? 'audio.mp3' : 'video.mp4';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(downloadUrl);
                
                clearInterval(progressInterval);
                document.getElementById('status').textContent = 'Download complete!';
            } catch (error) {
                clearInterval(progressInterval);
                document.getElementById('status').textContent = 'Error: ' + error.message;
            }
        }
        
        async function updateProgress() {
            const url = document.getElementById('urlInput').value;
            const response = await fetch('/progress?url=' + encodeURIComponent(url));
            const data = await response.json();
            
            const progressBar = document.getElementById('progressBar');
            const progressInfo = document.getElementById('progressInfo');
            
            progressBar.style.width = data.progress + '%';
            const eta = data.eta || '--:--';
            progressInfo.textContent = data.progress.toFixed(1) + '% - ' + eta + ' remaining';
            
            if (data.progress >= 100) {
                clearInterval(progressInterval);
            }
        }
    </script>
</body>
</html>'''

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE, session=session)

def get_youtube_client():
    if 'credentials' not in session:
        return None
    
    credentials_dict = session['credentials']
    credentials = Credentials(
        token=credentials_dict['token'],
        refresh_token=credentials_dict['refresh_token'],
        token_uri=credentials_dict['token_uri'],
        client_id=credentials_dict['client_id'],
        client_secret=credentials_dict['client_secret'],
        scopes=credentials_dict['scopes']
    )
    
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(GoogleRequest())
            session['credentials'] = credentials_to_dict(credentials)
    return credentials

@app.route('/info')
def get_info():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'})
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }

        # If user is authenticated, add their credentials
        credentials = get_youtube_client()
        if credentials:
            ydl_opts.update({
                'cookiefile': 'youtube.com_cookies.txt',
                'cookiesfrombrowser': ('chrome',),
            })

        with YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                return jsonify({
                    'title': info.get('title'),
                    'channel': info.get('uploader'),
                    'duration': info.get('duration'),
                    'thumbnail': info.get('thumbnail'),
                    'age_restricted': info.get('age_limit', 0) > 0
                })
            except Exception as e:
                if 'age-restricted' in str(e).lower() and not credentials:
                    return jsonify({
                        'error': 'This video is age-restricted. Please sign in with Google to access it.',
                        'requires_auth': True
                    })
                raise
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/auth/login')
def auth_login():
    # Start Google OAuth flow
    client_secrets = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRETS')
    if not client_secrets or not os.path.exists(client_secrets):
        return 'Server not configured for Google OAuth. Set GOOGLE_OAUTH_CLIENT_SECRETS to a client_secret.json path.', 500
    flow = Flow.from_client_secrets_file(
        client_secrets,
        scopes=['openid', 'https://www.googleapis.com/auth/userinfo.profile', 'https://www.googleapis.com/auth/userinfo.email']
    )
    flow.redirect_uri = url_for('auth_callback', _external=True)
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true', prompt='consent')
    session['oauth_state'] = state
    return redirect(authorization_url)

@app.route('/auth/callback')
def auth_callback():
    client_secrets = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRETS')
    if not client_secrets or not os.path.exists(client_secrets):
        return 'Server not configured for Google OAuth.', 500
    state = session.get('oauth_state')
    flow = Flow.from_client_secrets_file(
        client_secrets,
        scopes=['openid', 'https://www.googleapis.com/auth/userinfo.profile', 'https://www.googleapis.com/auth/userinfo.email'],
        state=state
    )
    flow.redirect_uri = url_for('auth_callback', _external=True)
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    # Store credentials in session (never store in codebase)
    session['google_credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes,
    }
    return redirect(url_for('home'))

@app.route('/progress')
def get_progress():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'})
    
    try:
        with YoutubeDL() as ydl:
            video_id = ydl.extract_info(url, download=False)['id']
            return jsonify({
                'progress': download_progress.get(video_id, 0),
                'speed': download_speed.get(video_id, 'N/A'),
                'eta': download_eta.get(video_id, 'N/A')
            })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/download', methods=['POST'])
def download():
    # Check authentication for age-restricted videos
    credentials = get_youtube_client()
    
    # Handle form-data
    if request.content_type and 'multipart/form-data' in request.content_type:
        url = request.form.get('url')
        format_type = request.form.get('format')
        quality = request.form.get('quality')
        fps = request.form.get('fps')
        audio_quality = request.form.get('audioQuality')
        api_key = request.form.get('apiKey')
    else:
        data = request.get_json(force=True, silent=True) or {}
        url = data.get('url')
        format_type = data.get('format')
        quality = data.get('quality')
        fps = data.get('fps')
        audio_quality = data.get('audioQuality')
        api_key = data.get('apiKey')
    
    # Set up cookies for authenticated requests
    cookies_file = None
    if credentials:
        cookies_file = os.path.join(os.path.dirname(__file__), 'youtube.com_cookies.txt')

    # API key check
    if VALID_API_KEYS and api_key not in VALID_API_KEYS:
        return 'Unauthorized: invalid API key', 401

    # Rate limiting by IP
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    limited, msg = is_rate_limited(client_ip)
    if limited:
        return msg, 429
    
    if not url:
        return 'No URL provided', 400
    
    try:
        temp_dir = tempfile.mkdtemp()
        ffmpeg_path = os.path.join(os.path.dirname(__file__), 'ffmpeg-master-latest-win64-gpl', 'bin')
        cookiefile_path = None
        # If Google OAuth session has credentials, we rely on authenticated cookies via yt-dlp later (cookiesfrombrowser)
        
        if format_type == 'audio':
            output_template = os.path.join(temp_dir, '%(title)s.%(ext)s')
            ydl_opts = {
                'format': 'bestaudio',
                'ffmpeg_location': ffmpeg_path,
                'outtmpl': output_template,
                'quiet': False,
                'progress_hooks': [progress_hook],
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': audio_quality,
                }],
            }
        else:
            output_template = os.path.join(temp_dir, '%(title)s_%(height)sp%(fps)s.%(ext)s')
            # Create format string based on quality and fps
            format_str = (
                f'bestvideo[height<={quality}][fps<={fps}][ext=mp4]+'
                'bestaudio[ext=m4a]/'
                f'bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/'
                f'best[height<={quality}]'
            )
            
            ydl_opts = {
                'format': format_str,
                'ffmpeg_location': ffmpeg_path,
                'outtmpl': output_template,
                'quiet': False,
                'progress_hooks': [progress_hook],
                'merge_output_format': 'mp4',
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }],
            }
        # Common hardening + aria2c (server-side: enable if available)
        ydl_opts = apply_common_ydl_hardening(ydl_opts, ffmpeg_path, cookiefile_path, use_aria2c=True)
        # Use local browser cookies if available (fixes age-restricted videos)
        try:
            # Prefer Chrome Default profile when available
            local = os.environ.get('LOCALAPPDATA') or ''
            chrome_profiles = os.path.join(local, 'Google', 'Chrome', 'User Data')
            if os.path.isdir(chrome_profiles):
                ydl_opts['cookiesfrombrowser'] = ('chrome', 'Default')
            else:
                # Try other Chromium-based or Firefox profiles
                roaming = os.environ.get('APPDATA') or ''
                if os.path.isdir(os.path.join(roaming, 'Mozilla', 'Firefox', 'Profiles')):
                    ydl_opts['cookiesfrombrowser'] = ('firefox',)
                elif os.path.isdir(os.path.join(local, 'Microsoft', 'Edge', 'User Data')):
                    ydl_opts['cookiesfrombrowser'] = ('edge', 'Default')
        except Exception:
            pass
        
        # Configure ffmpeg path
        ffmpeg_path = os.path.join(os.path.dirname(__file__), 'ffmpeg-master-latest-win64-gpl', 'bin')
        ydl_opts['ffmpeg_location'] = ffmpeg_path
        
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        # Find the downloaded file
        downloaded_file = None
        for file in os.listdir(temp_dir):
            if format_type == 'audio' and file.endswith('.mp3'):
                downloaded_file = os.path.join(temp_dir, file)
                break
            elif format_type == 'video' and file.endswith('.mp4'):
                downloaded_file = os.path.join(temp_dir, file)
                break
        
        if downloaded_file and os.path.exists(downloaded_file):
            return send_file(
                downloaded_file,
                as_attachment=True,
                download_name=os.path.basename(downloaded_file)
            )
        
        return 'Download failed', 500
    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    # Configure ffmpeg path
    ffmpeg_path = os.path.join(os.path.dirname(__file__), 'ffmpeg-master-latest-win64-gpl', 'bin')
    os.environ["PATH"] = ffmpeg_path + os.pathsep + os.environ["PATH"]
    # Init persistent rate limit DB
    init_db()
    app.run(debug=True, port=8501)
