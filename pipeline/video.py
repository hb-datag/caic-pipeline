"""Phase 4: FFmpeg assembly — intro -> branded slide -> meeting recording.

FAST PATH: if the meeting video is already H.264 + AAC (the normal case,
including 1080p/30), it is stream-copied untouched — only the short intro and
slide segments are encoded, generated to EXACTLY match the meeting's
resolution / fps / audio layout so concat can copy everything.

FALLBACK: anything else (VP9, HEVC, weird pixel formats…) re-encodes the
whole program to 1080p30 H.264/AAC.
"""

import json
import subprocess
from fractions import Fraction
from pathlib import Path

from . import slide as slide_mod

INTRO_SECONDS = 4
SLIDE_SECONDS = 7


def _run(cmd: list) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:8])}… :: "
                           f"{p.stderr[-400:]}")


def probe(path: str) -> dict:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", path],
        capture_output=True, text=True, check=True)
    info = json.loads(p.stdout)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    fps = float(Fraction(v.get("avg_frame_rate") or v["r_frame_rate"]))
    return {
        "w": v["width"], "h": v["height"], "fps": round(fps, 3),
        "vcodec": v["codec_name"], "pix_fmt": v.get("pix_fmt", ""),
        "acodec": a["codec_name"] if a else None,
        "sr": int(a["sample_rate"]) if a else 48000,
        "ch": int(a.get("channels", 2)) if a else 2,
        "duration": float(info["format"]["duration"]),
    }


def _still_to_clip(png: str, out: str, seconds: int, spec: dict) -> None:
    """Encode a still image into a video segment matching the meeting's specs."""
    _run([
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(spec["fps"]), "-i", png,
        "-f", "lavfi", "-i",
        f"anullsrc=channel_layout={'mono' if spec['ch'] == 1 else 'stereo'}"
        f":sample_rate={spec['sr']}",
        "-t", str(seconds),
        "-vf", f"scale={spec['w']}:{spec['h']},format=yuv420p",
        "-c:v", "libx264", "-profile:v", "high", "-preset", "medium",
        "-c:a", "aac", "-b:a", "128k", "-shortest", out,
    ])


def assemble(meeting_video: str, title: str, date: str, key_points: list,
             workdir: str, log=print):
    """Build final.mp4. Returns (final_path, offset_seconds, fast_path_used)."""
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    spec = probe(meeting_video)
    fast = spec["vcodec"] == "h264" and spec["acodec"] == "aac" and \
        spec["pix_fmt"] in ("yuv420p", "yuvj420p")
    log(f"Input: {spec['w']}x{spec['h']} {spec['fps']}fps "
        f"{spec['vcodec']}/{spec['acodec']} — "
        + ("stream-copy fast path" if fast else "re-encode fallback"))

    if not fast:  # normalize the target spec for the whole program
        spec = {**spec, "w": 1920, "h": 1080, "fps": 30, "sr": 48000, "ch": 2}

    size = (spec["w"], spec["h"])

    # 1. intro: real clip if provided, else generated placeholder title card
    def _exists(p: Path) -> bool:
        try:
            return p.exists()
        except OSError:
            return False

    intro_src = Path("/root/assets/caic_intro.mp4")
    if not _exists(intro_src):
        intro_src = Path("assets/caic_intro.mp4")  # local dev
    intro_seg = work / "seg_intro.mp4"
    if _exists(intro_src):
        _run(["ffmpeg", "-y", "-i", str(intro_src),
              "-vf", f"scale={spec['w']}:{spec['h']},fps={spec['fps']},format=yuv420p",
              "-c:v", "libx264", "-profile:v", "high", "-preset", "medium",
              "-c:a", "aac", "-b:a", "128k",
              "-ar", str(spec["sr"]), "-ac", str(spec["ch"]), str(intro_seg)])
        intro_dur = probe(str(intro_seg))["duration"]
    else:
        png = slide_mod.render_intro_placeholder(str(work / "intro.png"), size)
        _still_to_clip(png, str(intro_seg), INTRO_SECONDS, spec)
        intro_dur = INTRO_SECONDS

    # 2. branded key-points slide
    slide_png = slide_mod.render_slide(title, date, key_points,
                                       str(work / "slide.png"), size)
    slide_seg = work / "seg_slide.mp4"
    _still_to_clip(slide_png, str(slide_seg), SLIDE_SECONDS, spec)

    # 3. meeting segment
    if fast:
        meeting_seg = Path(meeting_video)
    else:
        meeting_seg = work / "seg_meeting.mp4"
        log("Re-encoding the recording to 1080p30 (this is the slow part)…")
        _run(["ffmpeg", "-y", "-i", meeting_video,
              "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
                     "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
              "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast",
              "-crf", "20", "-c:a", "aac", "-b:a", "160k",
              "-ar", "48000", "-ac", "2", str(meeting_seg)])

    # 4. concat (stream copy — segments share codec parameters)
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in
                           [intro_seg, slide_seg, meeting_seg]),
                   encoding="utf-8")
    final = work / "final.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-c", "copy", "-movflags", "+faststart", str(final)])

    offset = intro_dur + SLIDE_SECONDS
    log(f"Stitched: intro ({intro_dur:.0f}s) + slide ({SLIDE_SECONDS}s) + "
        f"recording ({spec['duration'] / 60:.0f} min)")
    return str(final), offset, fast


def _hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def build_youtube_text(title: str, date: str, analysis: dict,
                       offset_s: float, pages_url: str) -> str:
    """Paste-ready title, description, and chapter list for YouTube Studio."""
    lines = [
        "=== TITLE (paste into YouTube) ===",
        f"{title} | Cincinnati AI Catalyst — {date}",
        "",
        "=== DESCRIPTION ===",
        analysis["summary"].split("\n\n")[0],
        "",
        f"Full recap, decisions and action items: {pages_url}",
        "",
    ]
    chapters = analysis.get("chapters") or []
    if chapters:
        lines.append("Chapters:")
        lines.append("00:00 Intro")   # YouTube requires a chapter at 00:00
        for c in chapters:
            h, m, s = (["00", "00"] + c["start"].split(":"))[-3:]
            t = int(h) * 3600 + int(m) * 60 + int(s) + int(offset_s)
            lines.append(f"{_hms(t)} {c['title']}")
        lines.append("")
    lines += [
        "=== HOW TO UPLOAD (operator) ===",
        "1. Download final.mp4 from the run page",
        "2. YouTube Studio -> Create -> Upload video",
        "3. Paste the title and description above, publish",
        "4. Paste the watch URL back into a future run note (Phase 5 wiring)",
    ]
    return "\n".join(lines)
