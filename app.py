import os
import sys
import tempfile
import streamlit as st
import streamlit.components.v1 as components
from downloader import build_dynamic_quality_options, apply_common_ydl_hardening, is_aria2c_available
import requests
from pathlib import Path
import subprocess
import shutil
import re
import os

# Configure ffmpeg path
FFMPEG_BIN_DIR = os.path.join(os.path.dirname(__file__), 'ffmpeg-master-latest-win64-gpl', 'bin')
os.environ["PATH"] = FFMPEG_BIN_DIR + os.pathsep + os.environ.get("PATH", "")

try:
    from yt_dlp import YoutubeDL
except Exception:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp"])
    from yt_dlp import YoutubeDL

st.set_page_config(page_title="YouTube Downloader", page_icon="🎥", layout="wide")

# Configure yt-dlp with enhanced options for all videos
YDL_OPTS = {
    'format': 'bestvideo+bestaudio/best',
    'merge_output_format': 'mp4',
    'quiet': True,
    'no_warnings': True,
    'extract_flat': True,
    'ignoreerrors': True,
    'no_color': True,
    'age_limit': 99,  # Allow age-restricted videos
    'cookiesfrombrowser': ('chrome',),  # Try to get cookies from Chrome
}

def get_chrome_cookies():
    """Get cookies from Chrome by creating a fresh cookie file."""
    import datetime
    import browser_cookie3
    try:
        
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
            return None
    except Exception as e:
        return None

# Initialize session state for video info
if 'video_info' not in st.session_state:
    st.session_state['video_info'] = None

def extract_video_info(url):
    """Extract video information using yt-dlp"""
    try:
        with YoutubeDL(YDL_OPTS) as ydl:
            video_info = ydl.extract_info(url, download=False)
            if video_info:
                return {
                    'title': video_info.get('title', 'Unknown Title'),
                    'uploader': video_info.get('uploader', 'Unknown Uploader'),
                    'duration': int(video_info.get('duration', 0)),
                    'thumbnail': video_info.get('thumbnail'),
                    'formats': video_info.get('formats', []),
                }
    except Exception as e:
        st.error(f"Error fetching video info: {str(e)}")
        return None
    return None



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



# Create header
st.title("YouTube Downloader")
st.caption("Select video quality and FPS or extract MP3 with chosen bitrate. Progress shows percent and time remaining.")



# Simple browser detection
def detect_local_browsers() -> list[str]:
    """Return a list of browsers available on the system"""
    detected: list[str] = []
    local = os.environ.get('LOCALAPPDATA', '')
    roaming = os.environ.get('APPDATA', '')
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
            if cookie_file:
                YDL_OPTS['cookiefile'] = cookie_file
            
            info = extract_video_info(url)
            if not info:
                st.error("Could not fetch video information. Please check the URL and try again.")
                st.stop()
                
            info_progress.progress(60)
            _ = info.get('formats', [])
            info_progress.progress(100)
            info_status.write("Info loaded")
            st.session_state['video_info'] = info
        except Exception as e:
            info_status.write("")
            info_progress.progress(0)
            msg = str(e).lower()
            if ('age-restricted' in msg) or ('sign in to confirm your age' in msg):
                st.warning("This video is age-restricted and requires sign-in.")
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

            # Try to use cookies from browsers
            try:
                available_browsers = detect_local_browsers()
                if available_browsers:
                    # Let yt-dlp auto-detect profile for the first supported browser
                    first = 'chrome' if 'chrome' in available_browsers else available_browsers[0]
                    ydl_opts['cookiesfrombrowser'] = (first,)
            except Exception:
                pass

            last_downloaded = None

            # Download with yt-dlp
            try:
                before = set(os.listdir(output_dir))
                with YoutubeDL(ydl_opts) as ydl:
                    status_text.write("Downloading...")
                    ydl.download([url])
                
                # Find the downloaded file
                candidate = downloaded_path.get('path')
                if candidate and os.path.exists(candidate):
                    last_downloaded = candidate
                else:
                    after = set(os.listdir(output_dir))
                    new_files = list(after - before)
                    if new_files:
                        new_files.sort(key=lambda f: os.path.getmtime(os.path.join(output_dir, f)), reverse=True)
                        last_downloaded = os.path.join(output_dir, new_files[0])
            except Exception as e:
                err_msg = str(e).lower()
                if 'sign in to confirm your age' in err_msg or 'age-restricted' in err_msg:
                    st.warning("This video is age-restricted and requires sign-in.")
                    st.stop()
                raise

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
