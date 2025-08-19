import os
import shutil
from typing import Any, Dict, List, Tuple


def is_aria2c_available() -> bool:
    return shutil.which('aria2c') is not None


def human_size(num_bytes: float) -> str:
    try:
        num = float(num_bytes)
    except Exception:
        return "?"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} PB"


def estimate_format_size(fmt: Dict[str, Any], duration_sec: float | None) -> float | None:
    # Prefer exact sizes reported by yt-dlp
    for key in ("filesize", "filesize_approx"):
        if fmt.get(key):
            return float(fmt[key])
    # Fallback: estimate from tbr (in Kbps) and duration
    tbr = fmt.get("tbr")  # total bitrate in Kbps for this stream
    if tbr and duration_sec:
        try:
            return float(tbr) * 1000 / 8.0 * float(duration_sec)
        except Exception:
            return None
    return None


def build_dynamic_quality_options(info: Dict[str, Any]) -> List[Dict[str, Any]]:
    duration = info.get("duration")
    formats = info.get("formats") or []
    options: List[Dict[str, Any]] = []
    # Only video-only formats (no audio). We'll merge with bestaudio later.
    for f in formats:
        if not f or f.get("vcodec") in (None, "none"):
            continue
        if f.get("acodec") and f.get("acodec") != "none":
            # skip progressive when we want to combine with bestaudio; we still can allow it, but prefer video-only
            continue
        height = f.get("height") or "?"
        fps = f.get("fps") or "?"
        ext = f.get("ext") or "?"
        vcodec = f.get("vcodec") or "?"
        fmt_id = f.get("format_id") or f.get("format")
        if not fmt_id:
            continue
        size_bytes = estimate_format_size(f, duration)
        size_label = human_size(size_bytes) if size_bytes else "?"
        label = f"{height}p{int(fps) if isinstance(fps, (int, float)) else fps} {ext} {vcodec} ~{size_label}"
        options.append({
            "id": str(fmt_id),
            "label": label,
            "height": height,
            "fps": fps,
            "ext": ext,
            "vcodec": vcodec,
            "size_bytes": size_bytes,
        })
    # Deduplicate by (height, fps, ext, vcodec, id) order by height desc then fps desc
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for opt in sorted(options, key=lambda o: (int(o["height"]) if str(o["height"]).isdigit() else 0, int(o["fps"]) if str(o["fps"]).isdigit() else 0), reverse=True):
        key = (opt["id"], opt["height"], opt["fps"], opt["ext"], opt["vcodec"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(opt)
    return deduped


def apply_common_ydl_hardening(opts: Dict[str, Any], ffmpeg_dir: str, cookiefile_path: str | None, use_aria2c: bool) -> Dict[str, Any]:
    opts.update({
        'ffmpeg_location': ffmpeg_dir,
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'concurrent_fragment_downloads': 8,
        'restrictfilenames': True,
        'windowsfilenames': True,
    })
    if cookiefile_path:
        opts['cookiefile'] = cookiefile_path
    if use_aria2c and is_aria2c_available():
        # Use dict form to target aria2c specifically
        opts['external_downloader'] = 'aria2c'
        opts['external_downloader_args'] = {
            'aria2c': ['-x', '16', '-k', '1M', '--file-allocation=none']
        }
    return opts




