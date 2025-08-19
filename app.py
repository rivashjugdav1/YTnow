import os
import sys
import tempfile
import streamlit as st
import streamlit.components.v1 as components
import json
from downloader import build_dynamic_quality_options, apply_common_ydl_hardening, is_aria2c_available
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
import requests
from pathlib import Path
from requests.exceptions import RequestException
import subprocess
import shutil
import sqlite3
import re

# Configure ffmpeg path
FFMPEG_BIN_DIR = os.path.join(os.path.dirname(__file__), 'ffmpeg-master-latest-win64-gpl', 'bin')
os.environ["PATH"] = FFMPEG_BIN_DIR + os.pathsep + os.environ.get("PATH", "")

try:
    from yt_dlp import YoutubeDL
except Exception:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp"])
    from yt_dlp import YoutubeDL

st.set_page_config(page_title="YouTube Downloader", page_icon="🎥", layout="wide")

# OAuth Configuration
SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/youtube.force-ssl'
]

# Get OAuth credentials from Streamlit secrets
try:
    CLIENT_CONFIG = {
        "web": {
            "client_id": st.secrets["general"]["GOOGLE_CLIENT_ID"],
            "client_secret": st.secrets["general"]["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [st.secrets["general"].get("OAUTH_REDIRECT_URI", "https://y-tnow.streamlit.app")]
        }
    }
except Exception as e:
    st.error(f"""
    Error loading OAuth configuration. Please check your Streamlit secrets configuration.
    Make sure you have configured the following in your secrets.toml:
    
    [general]
    PRODUCTION = true
    GOOGLE_CLIENT_ID = "your-client-id"
    GOOGLE_CLIENT_SECRET = "your-client-secret"
    OAUTH_REDIRECT_URI = "https://y-tnow.streamlit.app"
    
    Current error: {str(e)}
    """)

# Enable insecure transport for local development
try:
    if not st.secrets["general"].get("PRODUCTION", False):
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    # If running locally without secrets
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context

def get_chrome_cookies():
    """Get cookies from Chrome by creating a fresh cookie file."""
    try:
        import datetime
        import browser_cookie3
        
        # Create a temporary cookie file
        cookie_file = os.path.join(tempfile.gettempdir(), 'youtube_cookies.txt')
        
        try:
            # Get cookies from Chrome specifically for YouTube
            chrome_cookies = list(browser_cookie3.chrome(domain_name='.youtube.com'))
            
            # Write cookies in Netscape format
            with open(cookie_file, 'w', encoding='utf-8') as f:
                f.write('# Netscape HTTP Cookie File\n')
                f.write('# https://curl.haxx.se/rfc/cookie_spec.html\n')
                f.write('# This is a generated file!  Do not edit.\n\n')
                
                for cookie in chrome_cookies:
                    secure = 'TRUE' if cookie.secure else 'FALSE'
                    domain = cookie.domain if cookie.domain.startswith('.') else '.' + cookie.domain
                    domain_specified = 'TRUE' if cookie.domain.startswith('.') else 'FALSE'
                    path = cookie.path or '/'
                    expires = int(cookie.expires) if cookie.expires else 0
                    
                    f.write(f'{domain}\t{domain_specified}\t{path}\t{secure}\t{expires}\t{cookie.name}\t{cookie.value}\n')
            
            return cookie_file
        except Exception as e:
            st.write(f"Debug: Could not extract Chrome cookies: {e}")
            
            # Fallback to basic consent cookies
            current_time = int(datetime.datetime.now().timestamp())
            try:
                with open(cookie_file, 'w', encoding='utf-8') as f:
                    f.write(f'''# Netscape HTTP Cookie File
# https://curl.haxx.se/rfc/cookie_spec.html
# This is a generated file!  Do not edit.

.youtube.com\tTRUE\t/\tFALSE\t{current_time + 3600}\tCONSENT\tYES+cb.20240101-18-p0.en+FX
.youtube.com\tTRUE\t/\tFALSE\t{current_time + 3600}\tGPS\t1
.youtube.com\tTRUE\t/\tFALSE\t{current_time + 3600}\tVISITOR_INFO1_LIVE\tdefault
.youtube.com\tTRUE\t/\tFALSE\t{current_time + 3600}\tYSC\tdefault
.youtube.com\tTRUE\t/\tFALSE\t{current_time + 3600}\tPREF\tf6=8''')
                return cookie_file
            except Exception as write_error:
                st.write(f"Debug: Could not write fallback cookie file: {write_error}")
                return None
    except Exception as e:
        st.write(f"Debug: Error setting up cookies: {e}")
        return None

# Initialize session state for auth
if 'oauth_state' not in st.session_state:
    st.session_state['oauth_state'] = None
if 'credentials' not in st.session_state:
    st.session_state['credentials'] = None
if 'user_info' not in st.session_state:
    st.session_state['user_info'] = None

# Function to create Google OAuth flow
def create_oauth_flow():
    if not CLIENT_CONFIG["web"]["client_id"] or not CLIENT_CONFIG["web"]["client_secret"]:
        st.error("Google OAuth credentials not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables.")
        st.stop()
    
    # For cloud deployment, always use the cloud URL
    redirect_uri = "https://y-tnow.streamlit.app"
    if not st.secrets["general"].get("PRODUCTION", False):
        # For local development
        redirect_uri = "http://localhost:8501"
    
    flow = Flow.from_client_config(
        client_config=CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    
    return flow

# Check for OAuth callback parameters
params = st.query_params
if 'code' in params and 'state' in params:
    try:
        flow = create_oauth_flow()
        # Reconstruct the full callback URL with all parameters
        callback_url = "&".join([f"{k}={v}" for k, v in params.items()])
        full_url = f"http://127.0.0.1:8501?{callback_url}"
        flow.fetch_token(authorization_response=full_url)
        credentials = flow.credentials
        
        # Store credentials in session state
        st.session_state['credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        
        # Get user info
        userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
        headers = {'Authorization': f'Bearer {credentials.token}'}
        response = requests.get(userinfo_url, headers=headers)
        if response.ok:
            st.session_state['user_info'] = response.json()
        
        # Clear the URL parameters and reload the page
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"OAuth callback failed: {e}")

def get_youtube_client():
    if 'credentials' not in st.session_state or not st.session_state['credentials']:
        return None
    
    credentials_dict = st.session_state['credentials']
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
            st.session_state['credentials'] = {
                'token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': credentials.scopes
            }
    return credentials

def extract_video_id(youtube_url: str) -> str | None:
    try:
        # Handles https://www.youtube.com/watch?v=ID and youtu.be/ID
        # First try standard watch URL format
        match = re.search(r"v=([\w-]{11})", youtube_url)
        if match:
            return match.group(1)
        # Then try youtu.be format, ignoring any parameters after the ID
        match = re.search(r"youtu\.be/([\w-]{11})(?:\?|$)", youtube_url)
        if match:
            return match.group(1)
        # If still no match, try more aggressive extraction of any 11-char ID
        match = re.search(r"(?:v=|/)(?P<id>[\w-]{11})(?:\?|&|/|$)", youtube_url)
        if match:
            return match.group('id')
    except Exception as e:
        st.write(f"Debug: Video ID extraction error: {str(e)}")
        return None
    return None

def parse_iso8601_duration(iso_duration: str) -> int:
    # Very small parser for patterns like PT1H2M3S / PT15M / PT45S
    hours = minutes = seconds = 0
    if not iso_duration or not iso_duration.startswith('PT'):
        return 0
    try:
        h = re.search(r"(\d+)H", iso_duration)
        m = re.search(r"(\d+)M", iso_duration)
        s = re.search(r"(\d+)S", iso_duration)
        hours = int(h.group(1)) if h else 0
        minutes = int(m.group(1)) if m else 0
        seconds = int(s.group(1)) if s else 0
        return hours * 3600 + minutes * 60 + seconds
    except Exception:
        return 0

def fetch_oembed_metadata(youtube_url: str) -> dict | None:
    try:
        oembed_url = "https://www.youtube.com/oembed"
        params = { 'url': youtube_url, 'format': 'json' }
        resp = requests.get(oembed_url, params=params, timeout=8, headers={
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36',
        })
        if not resp.ok:
            return None
        data = resp.json() or {}
        return {
            'title': data.get('title'),
            'uploader': data.get('author_name'),
            'duration': 0,
            'thumbnail': data.get('thumbnail_url'),
            'formats': [],
        }
    except Exception:
        return None

# Create login/logout UI
col1, col2 = st.columns([3, 1])
with col1:
    st.title("YouTube Downloader")
    st.caption("Select video quality and FPS or extract MP3 with chosen bitrate. Progress shows percent and time remaining.")

with col2:
    if st.session_state.get('credentials'):
        user_info = st.session_state.get('user_info', {})
        st.write(f"Welcome, {user_info.get('name', 'User')}!")
        if st.button("Logout"):
            st.session_state['credentials'] = None
            st.session_state['user_info'] = None
            st.experimental_rerun()
    else:
        # Single sign-in button that opens auth in same tab
        if st.button("Sign in with Google"):
            try:
                flow = create_oauth_flow()
                authorization_url, state = flow.authorization_url(
                    access_type='offline',
                    include_granted_scopes='true',
                    prompt='consent'
                )
                st.session_state['oauth_state'] = state
                
                # Simple redirect
                st.markdown(f'<meta http-equiv="refresh" content="0;url={authorization_url}">', unsafe_allow_html=True)
                st.markdown(f'''
                    ### Redirecting to Google Sign In...
                    If you are not redirected automatically, [click here]({authorization_url})
                    ''')
                st.stop()
            except Exception as e:
                st.error(f"Error during authentication setup: {str(e)}")
                st.stop()


def _windows_paths():
    local = os.environ.get('LOCALAPPDATA') or ''
    roaming = os.environ.get('APPDATA') or ''
    return local, roaming

def cleanup_cookies():
    try:
        cookies_file = os.path.join(os.path.dirname(__file__), 'youtube_cookies.txt')
        if os.path.exists(cookies_file):
            os.remove(cookies_file)
    except Exception:
        pass


# Remove the duplicate callback handler since we now handle it in the main flow

def get_chrome_profiles():
    local, _ = _windows_paths()
    chrome_path = os.path.join(local, 'Google', 'Chrome', 'User Data')
    profiles = []
    
    if os.path.exists(chrome_path):
        try:
            for item in os.listdir(chrome_path):
                if item.startswith('Profile ') or item == 'Default':
                    profile_path = os.path.join(chrome_path, item)
                    if os.path.isdir(profile_path) and os.path.exists(os.path.join(profile_path, 'Cookies')):
                        profiles.append(item)
        except Exception:
            pass
    return profiles

def get_chromium_profiles(browser_key: str) -> list[str]:
    local, roaming = _windows_paths()
    base = None
    if browser_key == 'chrome':
        base = os.path.join(local, 'Google', 'Chrome', 'User Data')
    elif browser_key == 'edge':
        base = os.path.join(local, 'Microsoft', 'Edge', 'User Data')
    elif browser_key == 'brave':
        base = os.path.join(local, 'BraveSoftware', 'Brave-Browser', 'User Data')
    elif browser_key in {'opera', 'opera_gx'}:
        base = os.path.join(roaming, 'Opera Software', 'Opera Stable')
    if not base or not os.path.isdir(base):
        return []
    names: list[str] = []
    try:
        # Put 'Default' first if exists
        default_path = os.path.join(base, 'Default')
        if os.path.isdir(default_path):
            names.append('Default')
        for item in os.listdir(base):
            if item.startswith('Profile '):
                profile_path = os.path.join(base, item)
                if os.path.isdir(profile_path):
                    names.append(item)
    except Exception:
        return names
    # Dedupe while preserving order
    seen = set()
    ordered: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered

def detect_local_browsers() -> list[str]:
    detected: list[str] = []
    local, roaming = _windows_paths()
    # Only include browsers that yt-dlp supports
    candidates: list[tuple[str, str]] = [
        ("chrome", os.path.join(local, 'Google', 'Chrome', 'User Data')),
        ("edge", os.path.join(local, 'Microsoft', 'Edge', 'User Data')),
        ("firefox", os.path.join(roaming, 'Mozilla', 'Firefox', 'Profiles')),
        ("opera", os.path.join(roaming, 'Opera Software', 'Opera Stable')),
        ("brave", os.path.join(local, 'BraveSoftware', 'Brave-Browser', 'User Data')),
    ]
    for key, path in candidates:
        try:
            if os.path.isdir(path) and any(True for _ in os.scandir(path)):
                detected.append(key)
        except Exception:
            pass
    # dedupe preserve order
    seen = set()
    ordered: list[str] = []
    for k in detected:
        if k not in seen:
            seen.add(k)
            ordered.append(k)
    return ordered

# URL input
url = st.text_input("Enter YouTube URL:", placeholder="https://www.youtube.com/watch?v=...")

# Initialize session state
if 'video_info' not in st.session_state:
    st.session_state['video_info'] = None

col_actions = st.columns([1, 2])
with col_actions[0]:
    get_info_clicked = st.button("Get Video Info")

if get_info_clicked:
    if not url:
        st.error("Please enter a valid YouTube URL.")
    else:
        info_progress = st.progress(0)
        info_status = st.empty()
        try:
            info_status.write("Fetching video info...")
            info_progress.progress(10)
            
            # Get cookies for authentication
            cookie_file = get_chrome_cookies()
            
            # Configure yt-dlp options with more detailed error handling and cookie support
            ydl_opts = {
                'quiet': True,
                'no_warnings': False,  # Enable warnings to see potential issues
                'noplaylist': True,
                'extract_flat': True,  # Only extract video metadata
                'format': 'best',  # Request best format for initial metadata
                'youtube_include_dash_manifest': False,  # Skip DASH manifest loading
                'ignoreerrors': True,  # Continue on error
                'no_color': True,  # Disable ANSI color codes
                'cookiesfrombrowser': ('chrome',),  # Try to get cookies from Chrome
                'cookiefile': cookie_file if cookie_file else None,  # Use our generated cookie file
                'age_limit': 99,  # Allow age-restricted videos
            }
            
            # Build info using the best source:
            # - If signed in: use YouTube Data API (avoids cookie/yt-dlp age prompts during info fetch)
            # - If not signed in: use yt-dlp unauthenticated
            credentials = get_youtube_client()
            if credentials:
                vid = extract_video_id(url)
                if vid:
                    api_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails&id={vid}"
                    headers = { 'Authorization': f"Bearer {credentials.token}" }
                    try:
                        resp = requests.get(api_url, headers=headers, timeout=10)
                        if not resp.ok:
                            raise Exception("API not enabled or error occurred")
                        data = resp.json() or {}
                        items = data.get('items') or []
                        if items:
                            item = items[0]
                            snippet = item.get('snippet', {})
                            content = item.get('contentDetails', {})
                            info = {
                                'title': snippet.get('title'),
                                'uploader': snippet.get('channelTitle'),
                                'duration': parse_iso8601_duration(content.get('duration', '')),
                                'thumbnail': (snippet.get('thumbnails', {}).get('high', {}) or snippet.get('thumbnails', {}).get('default', {})).get('url'),
                                'formats': [],
                            }
                        else:
                            raise Exception("No items found in API response")
                    except Exception:
                        info = None  # Reset info to ensure fallback
                else:
                    info = None
            
            # If API failed, fall back to yt-dlp
            if not info:
                info_status.write("Fetching video information...")
                try:
                    with YoutubeDL(ydl_opts) as ydl:
                        video_info = ydl.extract_info(url, download=False)
                        if video_info:
                            info = {
                                'title': video_info.get('title'),
                                'uploader': video_info.get('uploader'),
                                'duration': int(video_info.get('duration', 0)),
                                'thumbnail': video_info.get('thumbnail'),
                                'formats': video_info.get('formats', []),
                            }
                        else:
                            st.error("Could not fetch video information.")
                except Exception as ydl_error:
                    st.write(f"Debug: yt-dlp error: {str(ydl_error)}")
                
            # If both API and yt-dlp failed, try oEmbed as last resort
            if not info:
                    o = fetch_oembed_metadata(url)
                    if o:
                        info = o
                    else:
                        st.error("Failed to fetch video info.")
                        st.stop()
            else:
                try:
                    with YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                except Exception as e:
                    msg_low = str(e).lower()
                    if ('age-restricted' in msg_low) or ('sign in to confirm your age' in msg_low):
                        st.warning("Sign in to download age-restricted video.")
                        st.stop()
                    raise
                
            info_progress.progress(60)
            _ = info.get('formats', [])
            info_progress.progress(100)
            info_status.write("Info loaded")
            st.session_state['video_info'] = info
        except Exception as e:
            info_status.write("")
            info_progress.progress(0)
            cleanup_cookies()
            msg = str(e).lower()
            if ('age-restricted' in msg) or ('sign in to confirm your age' in msg):
                st.warning("Sign in to download age-restricted video.")
            else:
                st.error("Failed to fetch video info.")

info = st.session_state.get('video_info')

if info:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.image(info.get('thumbnail', ''), use_container_width=True)
    with col2:
        st.subheader(info.get('title', 'Unknown Title'))
        st.write(f"Channel: {info.get('uploader', 'Unknown')}")
        duration = info.get('duration') or 0
        st.write(f"Duration: {duration // 60}:{duration % 60:02d}")

    st.divider()

    # Options
    mode = st.selectbox("Download Mode", ["Video", "Audio Only (MP3)", "Audio Only (Original M4A/Opus)"])

    # Derive available qualities from formats, if desired
    only_available = st.checkbox("Only show available qualities", value=False)
    available_heights = sorted({f.get('height') for f in (info.get('formats') or []) if f.get('vcodec') and f.get('vcodec') != 'none' and f.get('height')}, reverse=True)
    available_fps = sorted({int(f.get('fps')) for f in (info.get('formats') or []) if f.get('vcodec') and f.get('vcodec') != 'none' and f.get('fps')}, reverse=True)
    fixed_heights = [2160, 1440, 1080, 720, 480]
    fixed_fps = [60, 30]
    height_options = [str(h) for h in (available_heights if (only_available and available_heights) else fixed_heights)]
    fps_options = [str(f) for f in (available_fps if (only_available and available_fps) else fixed_fps)]

    dynamic_opts = []
    use_dynamic_format_id = False
    if mode == "Video":
        use_dynamic_format_id = st.checkbox("Choose exact available format (faster & precise)", value=False)
        if use_dynamic_format_id:
            dynamic_opts = build_dynamic_quality_options(info)
            labels = [opt['label'] for opt in dynamic_opts] or ["No video formats listed"]
            selected_idx = st.selectbox("Available formats", list(range(len(labels))), format_func=lambda i: labels[i] if i < len(labels) else labels[0])
        else:
            quality = st.selectbox("Max Resolution", height_options, index=min(2, len(height_options)-1))
            fps_choice = st.selectbox("Max Frame Rate", fps_options, index=0)
    else:
        if mode == "Audio Only (MP3)":
            audio_quality = st.select_slider("MP3 Bitrate (kbps)", options=["128", "192", "256", "320"], value="320")

    # Save folder selection (default to Downloads)
    default_downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    if 'output_dir' not in st.session_state:
        st.session_state['output_dir'] = default_downloads
    st.session_state['output_dir'] = st.text_input("Save to folder", value=st.session_state['output_dir'])
    output_dir = st.session_state['output_dir']

    # Mobile-friendly spacing
    st.markdown("""
        <style>
          button[kind="primary"] { width: 100%; }
          .stDownloadButton { width: 100%; }
        </style>
    """, unsafe_allow_html=True)

    # Progress UI
    progress_bar = st.progress(0)
    progress_text = st.empty()
    info_line = st.empty()  # shows "XX% - mm:ss remaining" and final state
    status_text = st.empty()

    # Start download
    if st.button("Start Download"):
        # Validate/create output directory
        try:
            if not output_dir:
                output_dir = default_downloads
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            st.error(f"Invalid save folder: {e}")
            st.stop()

        # Output name pattern
        base_outtmpl = os.path.join(output_dir, '%(title)s.%(ext)s')

        def _format_eta(d):
            secs = d.get('eta')
            if isinstance(secs, (int, float)) and secs >= 0:
                mins = int(secs) // 60
                s = int(secs) % 60
                return f"{mins:02d}:{s:02d}"
            return (d.get('_eta_str') or d.get('eta_str') or 'N/A')

        downloaded_path = {'path': None}

        def progress_hook(d):
            if d.get('status') == 'downloading':
                try:
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes') or 0
                    percent = int(downloaded * 100 / total) if total else 0
                    progress_bar.progress(min(max(percent, 0), 100))
                    progress_text.markdown(f"**Progress:** {percent}%")
                    eta_fmt = _format_eta(d)
                    info_line.write(f"{percent}% - {eta_fmt} remaining")
                    status_text.write("Downloading...")
                except Exception:
                    pass
            elif d.get('status') == 'finished':
                progress_bar.progress(100)
                progress_text.markdown("**Progress:** 100%")
                info_line.write("100% - processing...")
                status_text.write("Processing...")
                # Capture filename if provided
                fn = d.get('filename')
                if fn:
                    downloaded_path['path'] = fn

        def postprocessor_hook(d):
            try:
                if d.get('status') == 'started':
                    status_text.write("Post-processing...")
                elif d.get('status') == 'finished':
                    status_text.write("Completed")
            except Exception:
                pass

        try:
            # Check if user is signed in
            if not st.session_state.get('credentials'):
                st.warning("⚠️ Please sign in with Google to download age-restricted videos")
                st.stop()

            if mode == "Audio Only (MP3)":
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'noplaylist': True,
                    'outtmpl': base_outtmpl,
                    'quiet': True,
                    'no_warnings': True,
                    'progress_hooks': [progress_hook],
                    'postprocessor_hooks': [postprocessor_hook],
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': audio_quality,
                    }],
                }
            elif mode == "Audio Only (Original M4A/Opus)":
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'noplaylist': True,
                    'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
                    'quiet': True,
                    'no_warnings': True,
                    'progress_hooks': [progress_hook],
                    'postprocessor_hooks': [postprocessor_hook],
                }
            else:
                if use_dynamic_format_id and dynamic_opts:
                    selected = dynamic_opts[selected_idx]
                    # exact format id for video + bestaudio
                    ydl_opts = {
                        'format': f"{selected['id']}+bestaudio/best",
                        'noplaylist': True,
                        'merge_output_format': 'mp4',
                        'outtmpl': os.path.join(output_dir, '%(title)s_%(height)sp%(fps)s.%(ext)s'),
                        'quiet': True,
                        'no_warnings': True,
                        'progress_hooks': [progress_hook],
                        'postprocessor_hooks': [postprocessor_hook],
                        'postprocessors': [{
                            'key': 'FFmpegVideoConvertor',
                            'preferedformat': 'mp4',
                        }],
                    }
                else:
                    format_str = (
                        f"bestvideo[height<={quality}][fps<={fps_choice}][ext=mp4]+bestaudio[ext=m4a]/"
                        f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/"
                        f"best[height<={quality}]"
                    )
                    ydl_opts = {
                        'format': format_str,
                        'noplaylist': True,
                        'merge_output_format': 'mp4',
                        'outtmpl': os.path.join(output_dir, '%(title)s_%(height)sp%(fps)s.%(ext)s'),
                        'quiet': True,
                        'no_warnings': True,
                        'progress_hooks': [progress_hook],
                        'postprocessor_hooks': [postprocessor_hook],
                        'postprocessors': [{
                            'key': 'FFmpegVideoConvertor',
                            'preferedformat': 'mp4',
                        }],
                    }

            # Common robustness + aria2c
            use_aria = st.checkbox("Use aria2c if available (faster)", value=is_aria2c_available())
            # Apply hardening (no cookie file used here)
            ydl_opts = apply_common_ydl_hardening(ydl_opts, FFMPEG_BIN_DIR, None, use_aria)
            # Add default headers for better compatibility
            ydl_opts.update({
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-us,en;q=0.5',
                    'Accept-Encoding': 'gzip,deflate',
                    'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7'
                }
            })

            # Use local browser cookies (fixes age-restricted videos)
            try:
                available_browsers = detect_local_browsers()
                if available_browsers:
                    # Let yt-dlp auto-detect profile for the first supported browser
                    first = 'chrome' if 'chrome' in available_browsers else available_browsers[0]
                    ydl_opts['cookiesfrombrowser'] = (first,)
            except Exception:
                pass

            last_downloaded = None

            def _attempt_download(opts):
                with YoutubeDL(opts) as ydl:
                    status_text.write("Downloading...")
                    before = set(os.listdir(output_dir))
                    ydl.download([url])
                    return before

            tried_browsers: list[str] = []
            download_succeeded = False
            try:
                before = _attempt_download(ydl_opts)
                download_succeeded = True
            except Exception as e:
                err_msg = str(e)
                # If cookie DB is locked OR DPAPI decryption fails, try alternatives
                if (
                    ('Could not copy' in err_msg and 'cookie database' in err_msg) or
                    ('Failed to decrypt with DPAPI' in err_msg)
                ):
                    chosen = None
                    cfb = ydl_opts.get('cookiesfrombrowser')
                    if isinstance(cfb, (list, tuple)) and cfb:
                        chosen = cfb[0]
                    if chosen:
                        tried_browsers.append(chosen)
                    for b in [b for b in detect_local_browsers() if b not in tried_browsers]:
                        chromium_like = {"chrome", "edge", "brave", "chromium", "opera", "opera_gx"}
                        if b in chromium_like:
                            profiles_to_try = get_chromium_profiles(b) or ['Default']
                            attempts = [None] + profiles_to_try
                            for prof in attempts:
                                if prof is None:
                                    ydl_opts['cookiesfrombrowser'] = (b,)
                                else:
                                    ydl_opts['cookiesfrombrowser'] = (b, prof)
                                try:
                                    before = _attempt_download(ydl_opts)
                                    download_succeeded = True
                                    break
                                except Exception as inner_e:
                                    if 'could not find' in str(inner_e).lower():
                                        continue
                                    else:
                                        continue
                            if download_succeeded:
                                break
                        else:
                            ydl_opts['cookiesfrombrowser'] = (b,)
                            try:
                                before = _attempt_download(ydl_opts)
                                download_succeeded = True
                                break
                            except Exception:
                                pass
                    if not download_succeeded:
                        # Last resort: try without cookies
                        ydl_opts.pop('cookiesfrombrowser', None)
                        before = _attempt_download(ydl_opts)
                        download_succeeded = True
                else:
                    # Friendly message if age restriction triggered
                    if ('sign in to confirm your age' in err_msg.lower()) or ('age-restricted' in err_msg.lower()):
                        st.warning("Sign in to download age-restricted video.")
                        st.stop()
                    raise
                # Try filename from hook first
                candidate = downloaded_path.get('path')
                if candidate and os.path.exists(candidate):
                    last_downloaded = candidate
                else:
                    after = set(os.listdir(output_dir))
                    new_files = list(after - before)
                    if new_files:
                        new_files.sort(key=lambda f: os.path.getmtime(os.path.join(output_dir, f)), reverse=True)
                        last_downloaded = os.path.join(output_dir, new_files[0])

            # Completed UI
            progress_bar.progress(100)
            progress_text.markdown("**Progress:** 100%")
            info_line.write("100% - complete")
            status_text.write("Completed")

            # Provide last file for direct download and open-folder action
            if last_downloaded and os.path.exists(last_downloaded):
                with open(last_downloaded, 'rb') as fh:
                    st.download_button(label="Download file", data=fh, file_name=os.path.basename(last_downloaded), mime="application/octet-stream")
                st.success(f"Saved to: {last_downloaded}")
                # Open folder button
                if st.button("Open folder"):
                    try:
                        folder = os.path.dirname(last_downloaded)
                        if os.name == 'nt':
                            os.startfile(folder)
                        elif sys.platform == 'darwin':
                            import subprocess
                            subprocess.Popen(['open', folder])
                        else:
                            import subprocess
                            subprocess.Popen(['xdg-open', folder])
                    except Exception:
                        pass
            else:
                st.error("Could not find the downloaded file.")
        except Exception as e:
            msg = str(e)
            if ('sign in to confirm your age' in msg.lower()) or ('age-restricted' in msg.lower()):
                st.warning("Sign in to download age-restricted video.")
            else:
                st.error("Download failed.")
