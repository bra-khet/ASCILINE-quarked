#!/usr/bin/env python3
"""
gradio_app.py — ASCILINE Studio
A clean, professional, local desktop-style GUI for the ASCILINE engine.

This is a single-file Gradio application that makes the full power of ASCILINE
(VideoDecoder + AsciiMapper + adaptive codec + re-encoding behavior) accessible
through a beautiful, simple, layman-friendly interface.

Run:
    python gradio_app.py

Extra deps (in addition to the project's existing requirements):
    pip install gradio pillow imageio

The app re-uses the exact engine core for 100% consistency:
- Every frame decode goes through VideoDecoder
- Every character mapping goes through AsciiMapper
- Re-encode visuals follow the low-res BGR blocks + optional cv2.putText overlays on black/BGRA (as established in prior pipeline work)
- Transcription formats exactly match the documented blocks / JSONL / per-frame behavior with color stripped by default
- Adaptive codec (codec.py) supported for optional ultra-compact binary archives
- stream_server.py launched for the real-time browser player tab

Workspace organization:
All outputs are written under your chosen workspace root into clear subfolders:
  llm_transcripts/, ascii_art/, ascii_clips/, etc.
Folders are auto-named with input stem + key settings + timestamp so everything is easy to find later.

Design goals:
- Extremely clean and uncluttered
- Plain human language on every control
- Professional dark theme with cyan/green accents
- One clear purpose per tab
- Generous previews and "open folder / download" actions everywhere
- Progress for long jobs
- No jargon

"""

import os
import sys
import json
import struct
import datetime
import tempfile
import shutil
import subprocess
import threading
import webbrowser
from pathlib import Path
from typing import Optional, List, Tuple, Any

import cv2
import numpy as np
import gradio as gr

# Pillow for nice still renders and transparent PNGs
from PIL import Image, ImageDraw, ImageFont

# imageio is optional but installed per instructions (useful for future seq work)
try:
    import imageio
except Exception:
    imageio = None

# === ENGINE REUSE (MANDATORY) ===
# We import and use these for EVERY frame operation to guarantee identical results
# to the rest of the ASCILINE tools (terminal player, web server, previous pipelines).
from ascii_video_player2 import VideoDecoder, AsciiMapper
from codec import encode_frame, TAG_RAW, TAG_ZLIB, TAG_DELTA


# =============================================================================
# INTERNAL UTILITIES (small, well-commented, match prior pipeline behavior)
# =============================================================================

def get_char_matrix(gray: np.ndarray, mapper: AsciiMapper) -> np.ndarray:
    """Exact same luminance-to-character logic used by AsciiMapper and the server."""
    indices = np.floor_divide(gray, max(1, 256 // mapper._n))
    np.clip(indices, 0, mapper._n - 1, out=indices)
    return mapper._lut[indices]


def get_color_matrix(bgr: np.ndarray, quantize_bits: int = 0) -> np.ndarray:
    """RGB color grid (quantized the same way the engine does when requested)."""
    rgb = bgr[:, :, ::-1].copy()
    if quantize_bits > 0:
        qb = quantize_bits
        rgb = (rgb >> qb) << qb
    return rgb


def render_ascii_frame_image(
    gray: np.ndarray,
    bgr: np.ndarray,
    mapper: AsciiMapper,
    style: str = "blocks",
    scale: int = 6,
    use_glyphs: bool = True,
) -> np.ndarray:
    """
    Render one low-res ASCILINE frame as a viewable RGB image on black.
    Follows the exact approach from the established pipeline (colored blocks + optional putText glyphs).
    This is what "Create ASCILINE Clip" and still previews use.
    """
    rows, cols = gray.shape
    out_h, out_w = rows * scale, cols * scale
    frame = np.zeros((out_h, out_w, 3), dtype=np.uint8)

    # The core "ASCILINE content" is the low-res color data (BGR)
    upscaled = cv2.resize(bgr, (out_w, out_h), interpolation=cv2.INTER_NEAREST)

    if style == "smooth blocks" or not use_glyphs:
        frame[:] = upscaled
        return frame

    # Colored blocks + character overlays (classic ASCII look)
    char_grid = get_char_matrix(gray, mapper)
    rgb_grid = get_color_matrix(bgr, quantize_bits=0)

    cell_h, cell_w = scale, scale
    font = cv2.FONT_HERSHEY_PLAIN
    font_scale = max(0.35, scale / 9.0)
    thickness = max(1, scale // 6)

    for r in range(rows):
        for c in range(cols):
            y0 = r * cell_h
            x0 = c * cell_w
            color = tuple(int(x) for x in rgb_grid[r, c])  # RGB

            # Solid colored block
            cv2.rectangle(frame, (x0, y0), (x0 + cell_w - 1, y0 + cell_h - 1), color, -1)

            # Overlay the letter (good contrast)
            ch = str(char_grid[r, c])
            lum = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
            txt_color = (0, 0, 0) if lum > 135 else (255, 255, 255)

            (tw, th), _ = cv2.getTextSize(ch, font, font_scale, thickness)
            tx = x0 + (cell_w - tw) // 2
            ty = y0 + (cell_h + th) // 2
            cv2.putText(frame, ch, (tx, ty), font, font_scale, txt_color, thickness, cv2.LINE_AA)

    return frame


def make_transparent_png(
    gray: np.ndarray, bgr: np.ndarray, mapper: AsciiMapper, scale: int = 4
) -> np.ndarray:
    """BGRA image with black fully transparent — perfect for --png-sequence --transparent path."""
    rows, cols = gray.shape
    out_h, out_w = rows * scale, cols * scale
    canvas = np.zeros((out_h, out_w, 4), dtype=np.uint8)

    upscaled = cv2.resize(bgr, (out_w, out_h), interpolation=cv2.INTER_NEAREST)
    canvas[:, :, :3] = upscaled

    # Alpha = 255 wherever there is any color (simple but effective)
    mask = (upscaled.sum(axis=2) > 0).astype(np.uint8) * 255
    canvas[:, :, 3] = mask
    return canvas


def get_specific_frame(video_path: str, time_sec: float, cols: int, rows: int) -> Tuple[np.ndarray, np.ndarray]:
    """
    Seek to a time and return (gray, bgr_small) exactly as VideoDecoder would.
    Used only for previews — full processing always uses the real VideoDecoder iterator.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        cap.release()
        raise FileNotFoundError(f"Could not open {video_path}")

    # Seek
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0, time_sec) * 1000.0)
    ok, frame = cap.read()
    if not ok:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = cap.read()
    cap.release()

    if not ok or frame is None:
        raise RuntimeError("Could not read a frame for preview")

    small = cv2.resize(frame, (cols, rows), interpolation=cv2.INTER_LINEAR)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return gray, small


def make_job_dir(workspace: str, category: str, stem: str, tag: str) -> Path:
    """Create a nicely named, timestamped output folder so files are trivial to organize and find later."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_tag = "".join(c for c in tag if c.isalnum() or c in "-_")[:40]
    out_dir = Path(workspace) / category / f"{stem}_{safe_tag}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def open_in_explorer(path: str):
    """Cross-platform friendly 'open folder' action. Creates the dir if it doesn't exist."""
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        if not p.is_dir():
            p = p.parent
        if p.exists():
            webbrowser.open(p.as_uri())
    except Exception:
        pass
    return None


def human_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def _get_video_path(file_obj: Any, local_str: str) -> Optional[str]:
    """Resolve a usable video path from either a Gradio File upload or a local path textbox.
    Prioritizes explicit local path if it exists.
    """
    if local_str and str(local_str).strip():
        p = Path(str(local_str).strip())
        if p.exists():
            return str(p)
    if file_obj is not None:
        if isinstance(file_obj, str):
            p = Path(file_obj)
            if p.exists():
                return str(p)
            return file_obj
        if hasattr(file_obj, "name"):
            p = Path(file_obj.name)
            if p.exists():
                return str(p)
            return file_obj.name
        try:
            s = str(file_obj)
            if s:
                return s
        except Exception:
            pass
    return None


# =============================================================================
# PIPELINE FUNCTIONS (modular, well-commented, reuse engine exactly)
# =============================================================================

def transcribe_for_llm(
    video_file,  # gr.File component (object with .name or None)
    local_path: str,
    workspace: str,
    cols: int,
    save_mode: str,
    include_color: bool,
    also_binary: bool,
    progress: gr.Progress = gr.Progress(),
) -> Tuple[str, Optional[str], str, str]:
    """
    Tab 1 core: clean character transcription (color stripped by default).
    Matches the exact behavior and file formats from the established transcribe_ascii.py.
    Also supports the adaptive codec for compact binary when requested.
    """
    video_path = _get_video_path(video_file, local_path)
    if not video_path:
        raise gr.Error("Please provide a video (upload or local path).")

    vpath = Path(video_path)
    stem = vpath.stem
    job_dir = make_job_dir(workspace, "llm_transcripts", stem, f"c{cols}")

    progress(0.05, desc="Opening video and calculating grid...")

    # Auto rows (same logic the whole engine uses)
    cap = cv2.VideoCapture(str(vpath))
    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1
    cap.release()
    rows = max(1, round(cols / (vw / max(vh, 1)) / 2))

    decoder = VideoDecoder(str(vpath), cols, rows, skip_gray=False)
    mapper = AsciiMapper()

    total = decoder.frame_count or 100
    fps = decoder.fps or 24.0

    progress(0.1, desc="Transcribing frames (characters only by default)...")

    primary_path = None
    created: List[Path] = []

    if save_mode.startswith("Single text") and not include_color:
        # Exact "blocks" format from the reference pipeline
        primary_path = job_dir / f"{stem}_c{cols}.txt"
        with open(primary_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("# ASCILINE TEXT TRANSCRIPT\n")
            f.write(f"# source_fps={fps:.3f}  grid={cols}x{rows}\n")
            f.write("# palette_size=93  color=stripped (recommended for LLM / archives)\n")
            f.write("# Characters capture shape + motion. Color is optional and much larger.\n\n")

            for i, (gray, bgr) in enumerate(decoder):
                chars = get_char_matrix(gray, mapper)
                block = "\n".join("".join(row) for row in chars)
                t = i / fps
                f.write(f"=== FRAME {i:05d} (t={t:.2f}s) ===\n{block}\n\n")
                if i % 20 == 0:
                    progress(0.1 + 0.8 * (i / max(total, 1)), desc=f"Frame {i}/{total}")
        created.append(primary_path)

    else:
        # JSONL (structured, great for code/AI). Matches reference exactly.
        primary_path = job_dir / f"{stem}_c{cols}.jsonl"
        with open(primary_path, "w", encoding="utf-8", newline="\n") as f:
            meta = {
                "format": "jsonl",
                "source_fps": fps,
                "cols": cols,
                "rows": rows,
                "color_included": include_color,
                "note": "Default to characters only for LLMs. Color bloats size/token count. Use codec.py for compact color deltas if needed.",
            }
            f.write(json.dumps({"meta": meta}) + "\n")

            for i, (gray, bgr) in enumerate(decoder):
                chars = get_char_matrix(gray, mapper)
                text_block = "\n".join("".join(row) for row in chars)
                rec: dict = {"frame": i, "t": round(i / fps, 3), "text": text_block}
                if include_color:
                    rgb = get_color_matrix(bgr, quantize_bits=3)
                    rec["colors"] = rgb.reshape(-1).tolist()
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if i % 20 == 0:
                    progress(0.1 + 0.8 * (i / max(total, 1)), desc=f"Frame {i}/{total}")
        created.append(primary_path)

    # Optional per-frame folder (simple and explicit)
    if save_mode.startswith("Folder of text"):
        frames_dir = job_dir / "frames"
        frames_dir.mkdir(exist_ok=True)
        # Re-decode (cheap) or cache — for simplicity we re-open; real users pick one format
        decoder2 = VideoDecoder(str(vpath), cols, rows)
        mapper2 = AsciiMapper()
        for i, (gray, bgr) in enumerate(decoder2):
            chars = get_char_matrix(gray, mapper2)
            block = "\n".join("".join(row) for row in chars)
            (frames_dir / f"{i:05d}.txt").write_text(block, encoding="utf-8")
        created.append(frames_dir)

    # Compact binary using the real adaptive codec (great for archives)
    if also_binary:
        progress(0.92, desc="Building compact binary archive with adaptive codec...")
        bin_path = job_dir / f"{stem}_c{cols}.asv"  # ASCILINE video archive
        meta_path = job_dir / f"{stem}_c{cols}_meta.json"

        decoder3 = VideoDecoder(str(vpath), cols, rows, skip_gray=False)
        mapper3 = AsciiMapper()
        prev = None
        frame_idx = 0

        with open(bin_path, "wb") as bf:
            for gray, bgr in decoder3:
                # Build the exact frame representation the codec expects
                indices = np.floor_divide(gray, max(1, 256 // mapper3._n))
                np.clip(indices, 0, mapper3._n - 1, out=indices)
                char_codes = np.array([ord(c) for c in mapper3._lut], dtype=np.uint8)[indices]

                rgb = bgr[:, :, ::-1]
                frame_buf = np.empty((rows, cols, 4), dtype=np.uint8)
                frame_buf[:, :, 0] = char_codes
                frame_buf[:, :, 1:] = rgb

                msg, prev = encode_frame(np.ascontiguousarray(frame_buf), prev, frame_idx)
                bf.write(struct.pack(">I", len(msg)))
                bf.write(msg)
                frame_idx += 1
                if frame_idx % 30 == 0:
                    progress(0.92 + 0.07 * (frame_idx / max(total, 1)), desc="Encoding compact frames...")

        meta = {
            "cols": cols,
            "rows": rows,
            "fps": fps,
            "nframes": frame_idx,
            "pixel": False,
            "codec": "adaptive (from codec.py)",
            "cell_bytes": 4,
            "note": "Decode with codec.makeDecoder(4). Each record is [uint32 len][message].",
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        created.extend([bin_path, meta_path])

    progress(1.0, desc="Done!")

    # Build friendly result UI
    rel_dir = str(job_dir.relative_to(Path(workspace).resolve())) if Path(workspace).exists() else str(job_dir)
    md = f"""## ✅ Transcription complete

**Saved in:** `{rel_dir}`

- Main output: **{primary_path.name}** ({human_size(primary_path.stat().st_size) if primary_path and primary_path.exists() else "ready"})
- All files are plain text or standard JSON — easy to open, search, git, or feed to any LLM.

**Why characters only (default)?**  
The letters alone carry the shapes, edges, and motion that matter for understanding and AI. This is dramatically smaller, cleaner, and more token-efficient than keeping color. Color is available when you really need it.

"""
    preview = ""
    if primary_path and primary_path.exists() and primary_path.suffix == ".txt":
        try:
            lines = primary_path.read_text(encoding="utf-8", errors="ignore").splitlines()[:12]
            preview = "\n".join(lines)
        except Exception:
            preview = "(preview unavailable)"

    return md, str(primary_path) if primary_path else None, str(job_dir), preview


def make_ascii_art(
    video_file,
    local_path: str,
    workspace: str,
    cols: int,
    time_sec: float,
    save_text: bool,
    save_png: bool,
    progress: gr.Progress = gr.Progress(),
) -> Tuple[str, str, str, Any, Any, str]:
    """
    Tab 2: Extract and save a specific frame as clean ASCII art (text + optional pretty visual PNG).
    Resolution (cols) is the primary creative control. Color is secondary.
    """
    video_path = _get_video_path(video_file, local_path)
    if not video_path:
        raise gr.Error("Please provide a video.")

    vpath = Path(video_path)
    stem = vpath.stem
    job_dir = make_job_dir(workspace, "ascii_art", stem, f"frame{int(time_sec)}s_c{cols}")

    progress(0.1, desc="Extracting chosen frame...")
    rows = max(1, round(cols / (1920 / 1080) / 2))  # reasonable default aspect
    try:
        gray, bgr_small = get_specific_frame(str(vpath), time_sec, cols, rows)
    except Exception as e:
        raise gr.Error(f"Could not extract frame: {e}")

    mapper = AsciiMapper()
    chars = get_char_matrix(gray, mapper)

    # Original thumbnail (small)
    orig_small = cv2.resize(bgr_small, (min(320, cols * 3), min(180, rows * 3)))
    orig_rgb = cv2.cvtColor(orig_small, cv2.COLOR_BGR2RGB)

    # ASCII visual (blocks + light glyphs for preview)
    preview_img = render_ascii_frame_image(gray, bgr_small, mapper, style="colored letters", scale=5, use_glyphs=True)
    preview_rgb = cv2.cvtColor(preview_img, cv2.COLOR_BGR2RGB)

    created_text = None
    created_png = None

    if save_text:
        progress(0.6, desc="Saving text...")
        txt_path = job_dir / f"{stem}_frame{int(time_sec)}s_c{cols}.txt"
        block = "\n".join("".join(row) for row in chars)
        txt_path.write_text(f"# ASCILINE ASCII ART\n# {vpath.name} @ {time_sec:.2f}s  grid={cols}x{rows}\n\n{block}", encoding="utf-8")
        created_text = str(txt_path)

    if save_png:
        progress(0.8, desc="Rendering pretty PNG...")
        # Use PIL for a clean monospace text render (classic look)
        png_path = job_dir / f"{stem}_frame{int(time_sec)}s_c{cols}.png"
        h, w = gray.shape
        # Try to find a decent monospace font
        font_size = 12
        font = None
        for fp in [
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/cour.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/System/Library/Fonts/Monaco.dfont",
        ]:
            if Path(fp).exists():
                try:
                    font = ImageFont.truetype(fp, font_size)
                    break
                except Exception:
                    pass
        if font is None:
            font = ImageFont.load_default()

        char_w, char_h = 7, 12  # approximate for the font size we chose
        img_w, img_h = w * char_w, h * char_h
        im = Image.new("RGB", (img_w, img_h), (8, 8, 10))
        draw = ImageDraw.Draw(im)
        for r, row in enumerate(chars):
            draw.text((0, r * char_h), "".join(row), fill=(230, 230, 230), font=font)
        im.save(png_path)
        created_png = str(png_path)

    progress(1.0, desc="Done!")

    md = f"""## ✅ ASCII art extracted

**Location:** `{job_dir}`

- Text file: {Path(created_text).name if created_text else 'not saved'}
- Visual PNG: {Path(created_png).name if created_png else 'not saved'}

The letters are generated with the exact same logic the entire ASCILINE engine uses.
"""
    return md, created_text or "", created_png or "", orig_rgb, preview_rgb, str(job_dir)


def create_asciiline_clip(
    video_file,  # gr.File
    local_path: str,
    workspace: str,
    cols: int,
    style: str,
    scale: int,
    include_audio: bool,
    make_transparent_seq: bool,
    progress: gr.Progress = gr.Progress(),
) -> Tuple[str, Optional[str], str, str]:
    """
    Tab 3: Full re-encode pipeline producing a standard video (or PNG sequence) whose visuals
    ARE the ASCILINE representation on black (or transparent).
    Previews in the UI let you compare resolutions and styles before the long render.
    """
    video_path = _get_video_path(video_file, local_path)
    if not video_path:
        raise gr.Error("Please provide a video.")

    vpath = Path(video_path)
    stem = vpath.stem
    style_key = style.lower().replace(" ", "_")
    job_dir = make_job_dir(workspace, "ascii_clips", stem, f"c{cols}_{style_key}")

    progress(0.02, desc="Preparing decoder (re-using the real engine core)...")

    # Auto rows
    cap_probe = cv2.VideoCapture(str(vpath))
    vw = int(cap_probe.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
    vh = int(cap_probe.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 360
    fps = cap_probe.get(cv2.CAP_PROP_FPS) or 24.0
    cap_probe.release()

    rows = max(1, round(cols / (vw / max(vh, 1)) / 2))

    decoder = VideoDecoder(str(vpath), cols, rows, skip_gray=False)
    mapper = AsciiMapper()

    total = decoder.frame_count or 100
    out_w = cols * scale
    out_h = rows * scale

    use_glyphs = "letters" in style.lower()
    pixel_style = "blocks" in style.lower() and not use_glyphs

    # Video writer (standard MP4 on black)
    video_path_out = job_dir / f"{stem}_c{cols}_{style_key}.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path_out), fourcc, fps, (out_w, out_h))
    if not writer.isOpened():
        raise RuntimeError("Could not open video writer. Try installing codecs or use the PNG sequence option.")

    png_dir = None
    if make_transparent_seq:
        png_dir = job_dir / "frames_png"
        png_dir.mkdir(exist_ok=True)

    prev = None  # for optional codec, not used in visual render
    frame_idx = 0

    progress(0.05, desc="Rendering ASCILINE frames...")

    for gray, bgr in decoder:
        # Visual frame exactly as the established pipeline does it
        vis = render_ascii_frame_image(
            gray, bgr, mapper,
            style="smooth blocks" if pixel_style else "colored letters",
            scale=scale,
            use_glyphs=use_glyphs
        )
        writer.write(vis)

        if png_dir:
            tpng = make_transparent_png(gray, bgr, mapper, scale=scale)
            cv2.imwrite(str(png_dir / f"frame_{frame_idx:05d}.png"), tpng)

        frame_idx += 1
        if frame_idx % 5 == 0:
            progress(0.05 + 0.9 * (frame_idx / max(total, 1)), desc=f"Frame {frame_idx}/{total}")

    writer.release()

    final_video = video_path_out
    if include_audio:
        progress(0.96, desc="Adding original audio (ffmpeg)...")
        audio_out = job_dir / f"{stem}_c{cols}_{style_key}_with_audio.mp4"
        try:
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(video_path_out),
                "-i", str(vpath),
                "-c:v", "copy", "-c:a", "copy",
                "-map", "0:v:0", "-map", "1:a:0",
                str(audio_out)
            ]
            subprocess.run(cmd, check=True, timeout=120)
            final_video = audio_out
        except Exception as e:
            # Non-fatal — user still has the silent version
            (job_dir / "audio_note.txt").write_text(f"Could not add audio: {e}\nffmpeg is required for audio passthrough.")

    progress(1.0, desc="Finished!")

    md = f"""## ✅ ASCILINE clip created

**Output folder:** `{job_dir}`

- Main video: **{final_video.name}** (play it in the player below or any video app)
- Style: {style}
- Resolution: {cols} columns → {out_w}×{out_h} pixels at scale ×{scale}
- Transparent PNG sequence: {'yes (in frames_png/)' if png_dir else 'no'}

You can now use the transparent frames + ffmpeg to create alpha video in any format you like (webm, prores, etc.).
"""
    return md, str(final_video), str(job_dir), "Video ready for preview above."


def launch_browser_player(
    source_type: str,
    video_path: str,
    folder_path: str,
    playlist_path: str,
    cols: int,
    mode: int,
    pixel: bool,
    vol: int,
    loop: bool,
    port: int,
    workspace: str,
    current_proc: Any,
) -> Tuple[str, str, Any]:
    """
    Tab 4: Launch the real existing stream_server.py in the background.
    Uses the exact same command-line interface the user already knows.
    The stdin pipe trick keeps the child's command_loop from killing the uvicorn thread.
    """
    if current_proc is not None:
        try:
            current_proc.terminate()
            current_proc.wait(timeout=3)
        except Exception:
            pass

    cmd = [sys.executable, "stream_server.py"]

    stable_video = None
    if source_type == "Single video":
        if not video_path:
            raise gr.Error("Please provide a video path or upload.")
        vp = Path(video_path)
        if not vp.exists():
            # If it was a temp upload, copy it to workspace so the server can use it reliably
            stable_video = Path(workspace) / "_uploads" / vp.name
            stable_video.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(vp, stable_video)
            vp = stable_video
        cmd.append(str(vp))
    elif source_type == "Folder of videos":
        if not folder_path or not Path(folder_path).exists():
            raise gr.Error("Please provide a valid folder path.")
        cmd.extend(["--folder", folder_path])
    else:  # Playlist
        if not playlist_path or not Path(playlist_path).exists():
            raise gr.Error("Please provide a valid playlist.json path.")
        cmd.extend(["--playlist", playlist_path])

    cmd.extend(["--cols", str(cols), "--mode", str(mode), "--vol", str(vol), "--port", str(port)])
    if pixel:
        cmd.append("--pixel")
    if loop:
        cmd.append("--loop")

    # Launch in background child process. Leave stdin pipe open so the child's input() blocks
    # while the daemon uvicorn thread keeps serving. This is the reliable non-blocking trick.
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=Path(__file__).parent,
        )
    except Exception as e:
        raise gr.Error(f"Failed to launch server: {e}")

    url = f"http://127.0.0.1:{port}"
    status = f"""**Server started in background.**

URL: {url}

- Open the link in any browser (Chrome/Edge/Firefox recommended).
- Click the big play button on the page.
- For full control (/status, /help, bandwidth debug, etc.) run the same command in a regular terminal instead.

The server will keep running until you click **Stop server** or close this Gradio app.
"""
    return status, url, proc


def stop_server(current_proc: Any) -> Tuple[str, Any]:
    if current_proc is not None:
        try:
            current_proc.terminate()
            current_proc.wait(timeout=4)
        except Exception:
            try:
                current_proc.kill()
            except Exception:
                pass
    return "Server stopped.", None


# =============================================================================
# GRADIO UI — CLEAN PROFESSIONAL DARK LAYOUT
# =============================================================================

DARK_CSS = """
.gradio-container { background-color: #0a0a0c !important; color: #e0e0e0 !important; }
.gradio-container .prose, .gradio-container label, .gradio-container .gr-text { color: #e0e0e0 !important; }
.gradio-container .gr-button.primary { background-color: #00ff5d !important; color: #0a0a0c !important; font-weight: 600; border: none; }
.gradio-container .gr-button { background-color: #1f1f24; color: #e0e0e0; border: 1px solid #333; }
.gradio-container .gr-button:hover { border-color: #00e5ff; }
.gradio-container .gr-tab { background-color: #111113; border-color: #222; }
.gradio-container .gr-tab.selected { border-bottom: 3px solid #00e5ff; color: #00e5ff; }
.gradio-container .gr-accordion { background-color: #111113; border: 1px solid #222; }
.gradio-container .gr-box, .gradio-container .gr-form { background-color: #111113; border: 1px solid #222; }
.gr-video, .gr-image, .gr-textbox, .gr-slider { background-color: #0f0f12 !important; }
footer { display: none !important; }
"""

def build_ui():
    with gr.Blocks(
        title="ASCILINE Studio",
    ) as demo:
        gr.Markdown(
            "# ASCILINE Studio\n"
            "**Turn any video into clean text for AI and archives, or beautiful ASCII clips.**\n"
            "Everything uses the real engine so results match the command-line tools exactly."
        )

        # === GLOBAL WORKSPACE (always visible, top priority for file-system happiness) ===
        with gr.Row():
            workspace = gr.Textbox(
                value="asciline_outputs",
                label="Workspace root folder",
                info="All results go into organized subfolders inside this folder (llm_transcripts/, ascii_art/, ascii_clips/, etc.). Change anytime.",
                scale=4
            )
            gr.Button("📁 Open workspace", size="sm", scale=1).click(
                fn=lambda w: open_in_explorer(w), inputs=[workspace], outputs=[]
            )

        gr.Markdown("---")

        with gr.Tabs():
            # ------------------------------------------------------------------
            # TAB 1: Transcribe for LLM
            # ------------------------------------------------------------------
            with gr.TabItem("1. Transcribe for LLM"):
                gr.Markdown("**Purpose:** Convert video into pure text (letters only by default) that is tiny, searchable, git-friendly, and perfect for LLMs and long-term archives.")
                gr.Markdown("The letters capture the shapes and motion. Color is extra data that makes everything much bigger — only turn it on when you truly need it.")

                with gr.Row():
                    t1_video = gr.File(label="Upload video", file_types=[".mp4", ".mov", ".mkv", ".avi", ".webm"], scale=2)
                    t1_local = gr.Textbox(label="Or paste full local path (recommended for big files)", placeholder="C:\\Videos\\myclip.mp4", scale=3)

                t1_cols = gr.Slider(60, 320, value=160, step=10, label="Character columns (more = sharper detail, bigger files, slower)")

                t1_save_mode = gr.Radio(
                    ["Single text file with frame markers (easiest to read and search)",
                     "JSON Lines file (structured — best for code and AI tools)",
                     "Folder of text files (one clean file per frame)"],
                    value="Single text file with frame markers (easiest to read and search)",
                    label="How do you want the characters saved?"
                )

                with gr.Accordion("Color and compact archive options (advanced)", open=False):
                    t1_include_color = gr.Checkbox(False, label="Include color data? (OFF by default — strongly recommended for LLMs)")
                    t1_binary = gr.Checkbox(False, label="Also create a compact binary archive using the engine's adaptive codec (excellent for long-term storage)")

                t1_btn = gr.Button("Transcribe Video", variant="primary", size="lg")

                t1_status = gr.Markdown()
                t1_main_file = gr.File(label="Download main transcript", interactive=False)
                t1_preview = gr.Textbox(label="Preview (first frames)", lines=8, max_lines=12)
                t1_folder = gr.Textbox(label="Output folder (copy this path)", interactive=False)
                gr.Button("📁 Open output folder", size="sm").click(fn=lambda p: open_in_explorer(p), inputs=[t1_folder], outputs=[])

                t1_btn.click(
                    fn=transcribe_for_llm,
                    inputs=[t1_video, t1_local, workspace, t1_cols, t1_save_mode, t1_include_color, t1_binary],
                    outputs=[t1_status, t1_main_file, t1_folder, t1_preview]
                )

            # ------------------------------------------------------------------
            # TAB 2: Make ASCII Art (stills)
            # ------------------------------------------------------------------
            with gr.TabItem("2. Make ASCII Art"):
                gr.Markdown("**Purpose:** Pull out one exact moment as clean ASCII art (text you can copy + a nice visual preview image). Resolution is the main creative knob.")

                with gr.Row():
                    t2_video = gr.File(label="Upload video", file_types=["video"], scale=2)
                    t2_local = gr.Textbox(label="Or local path", placeholder="C:\\Videos\\clip.mp4", scale=3)

                t2_cols = gr.Slider(40, 280, value=120, step=10, label="Character columns — this is the most important control")

                with gr.Row():
                    t2_time = gr.Number(value=5.0, label="Time in seconds", precision=2)
                    t2_frame_btn = gr.Button("Show this frame", scale=1)

                with gr.Row():
                    t2_orig = gr.Image(label="Original (small)", scale=1)
                    t2_ascii_vis = gr.Image(label="ASCII visual (this is what the letters look like)", scale=1)

                t2_ascii_text = gr.Textbox(label="Copyable ASCII text (monospace)", lines=12, max_lines=16)

                with gr.Accordion("Quick preview at different widths (same frame)", open=True):
                    t2_preview_btn = gr.Button("Generate width previews (80 / 120 / 160 / 240 cols)")
                    t2_previews = gr.Gallery(label="Same moment at different resolutions", columns=4, height="auto")

                with gr.Row():
                    t2_save_text = gr.Checkbox(True, label="Save text file")
                    t2_save_png = gr.Checkbox(True, label="Save pretty PNG render")

                t2_btn = gr.Button("Save this ASCII art", variant="primary")

                t2_status = gr.Markdown()
                t2_out_txt = gr.File(label="Text file", interactive=False)
                t2_out_png = gr.File(label="PNG render", interactive=False)
                t2_art_folder = gr.Textbox(label="Output folder")
                gr.Button("📁 Open folder", size="sm").click(fn=lambda p: open_in_explorer(p), inputs=[t2_art_folder], outputs=[])

                def _preview_widths(video, local, cols_base, time):
                    # Simplified: just call the single-frame extractor at several widths and render
                    vp = local or (video.name if video else None)
                    if not vp:
                        return []
                    results = []
                    for c in [80, 120, 160, 240]:
                        try:
                            g, b = get_specific_frame(vp, float(time or 5), c, max(1, round(c / 2.5)))
                            m = AsciiMapper()
                            img = render_ascii_frame_image(g, b, m, "colored letters", scale=4, use_glyphs=True)
                            results.append((cv2.cvtColor(img, cv2.COLOR_BGR2RGB), f"{c} cols"))
                        except Exception:
                            pass
                    return results

                t2_preview_btn.click(_preview_widths, [t2_video, t2_local, t2_cols, t2_time], t2_previews)

                def _do_preview(video, local, cols, time):
                    vp = local or (video.name if video else None)
                    if not vp:
                        raise gr.Error("Provide a video")
                    g, b = get_specific_frame(vp, float(time or 5), int(cols), max(1, round(int(cols) / 2.5)))
                    m = AsciiMapper()
                    vis = render_ascii_frame_image(g, b, m, "colored letters", scale=5, use_glyphs=True)
                    block = "\n".join("".join(row) for row in get_char_matrix(g, m))
                    orig = cv2.cvtColor(cv2.resize(b, (320, 180)), cv2.COLOR_BGR2RGB)
                    return orig, vis, block

                t2_frame_btn.click(_do_preview, [t2_video, t2_local, t2_cols, t2_time], [t2_orig, t2_ascii_vis, t2_ascii_text])

                t2_btn.click(
                    fn=make_ascii_art,
                    inputs=[t2_video, t2_local, workspace, t2_cols, t2_time, t2_save_text, t2_save_png],
                    outputs=[t2_status, t2_out_txt, t2_out_png, t2_orig, t2_ascii_vis, t2_art_folder]
                )

            # ------------------------------------------------------------------
            # TAB 3: Create ASCILINE Clip (full re-encode)
            # ------------------------------------------------------------------
            with gr.TabItem("3. Create ASCILINE Clip"):
                gr.Markdown("**Purpose:** Turn a whole video into a normal playable video file (or transparent frames) where the picture is made of the engine's ASCII representation.")

                with gr.Row():
                    t3_video = gr.File(label="Upload video", file_types=["video"], scale=2)
                    t3_local = gr.Textbox(label="Or local path", placeholder="C:\\Videos\\longclip.mp4", scale=3)

                t3_cols = gr.Slider(80, 400, value=160, step=10, label="Character columns (preview different values below before rendering the full thing)")

                t3_style = gr.Radio(
                    ["Classic letters", "Colored letters", "Smooth colored blocks (no letters)"],
                    value="Colored letters",
                    label="Visual style (plain language)"
                )

                with gr.Row():
                    t3_scale = gr.Slider(2, 12, value=6, step=1, label="Block size in final video (higher = bigger, easier to see letters)")
                    t3_preview_time = gr.Number(3.0, label="Preview time (seconds)", precision=1)

                t3_preview_btn = gr.Button("Preview this resolution + style (recommended before full render)")
                t3_preview_img = gr.Image(label="Preview at current settings", height=320)

                with gr.Accordion("More options", open=False):
                    t3_audio = gr.Checkbox(True, label="Include original audio in the final clip (requires ffmpeg)")
                    t3_transparent = gr.Checkbox(False, label="Also write transparent PNG sequence (best for alpha video later)")

                t3_btn = gr.Button("Create full ASCILINE video", variant="primary", size="lg")

                t3_status = gr.Markdown()
                t3_video_out = gr.Video(label="Your ASCILINE clip")
                t3_clip_folder = gr.Textbox(label="Output folder (contains video + any PNG sequence)")
                gr.Button("📁 Open folder", size="sm").click(fn=lambda p: open_in_explorer(p), inputs=[t3_clip_folder], outputs=[])

                def _clip_preview(v, local, cols, style, scale, t):
                    vp = local or (v.name if v else None)
                    if not vp:
                        return None
                    g, b = get_specific_frame(vp, float(t or 3), int(cols), max(1, round(int(cols) / 2.2)))
                    m = AsciiMapper()
                    sty = "smooth blocks" if "blocks" in style.lower() else "colored letters"
                    img = render_ascii_frame_image(g, b, m, sty, int(scale), use_glyphs="letters" in style.lower())
                    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

                t3_preview_btn.click(_clip_preview, [t3_video, t3_local, t3_cols, t3_style, t3_scale, t3_preview_time], t3_preview_img)

                t3_btn.click(
                    fn=create_asciiline_clip,
                    inputs=[t3_video, t3_local, workspace, t3_cols, t3_style, t3_scale, t3_audio, t3_transparent],
                    outputs=[t3_status, t3_video_out, t3_clip_folder]
                )

            # ------------------------------------------------------------------
            # TAB 4: Play in Browser (real engine)
            # ------------------------------------------------------------------
            with gr.TabItem("4. Play in Browser"):
                gr.Markdown("**Purpose:** Launch the original real-time web player (stream_server.py) exactly as you use it from the terminal, but controlled from here.")
                gr.Markdown("The server runs in the background. Use the URL in any browser. For the full interactive commands (/status, bandwidth, etc.) use a normal terminal instead.")

                t4_source = gr.Radio(["Single video", "Folder of videos", "Playlist JSON"], value="Single video", label="What do you want to play?")

                with gr.Row():
                    t4_video = gr.File(label="Video (upload or use path below)", file_types=["video"], visible=True)
                    t4_local = gr.Textbox(label="Local video path", visible=True)
                    t4_folder = gr.Textbox(label="Folder path", visible=False)
                    t4_playlist = gr.Textbox(label="playlist.json path", visible=False)

                def _toggle_source(choice):
                    return {
                        t4_video: gr.update(visible=(choice == "Single video")),
                        t4_local: gr.update(visible=(choice == "Single video")),
                        t4_folder: gr.update(visible=(choice == "Folder of videos")),
                        t4_playlist: gr.update(visible=(choice == "Playlist JSON")),
                    }

                t4_source.change(_toggle_source, t4_source, [t4_video, t4_local, t4_folder, t4_playlist])

                with gr.Row():
                    t4_cols = gr.Slider(80, 400, value=200, step=10, label="Character columns")
                    t4_mode = gr.Slider(1, 5, value=3, step=1, label="Color mode (1=B&W ... 5=16M colors)")
                    t4_pixel = gr.Checkbox(False, label="Pixel mode (colored blocks instead of letters)")

                with gr.Row():
                    t4_vol = gr.Slider(0, 5, value=1, step=1, label="Volume (0 = silent, 5 = loud)")
                    t4_loop = gr.Checkbox(True, label="Loop the playlist / folder")
                    t4_port = gr.Number(8000, label="Port", precision=0)

                t4_launch = gr.Button("Launch server in background", variant="primary", size="lg")
                t4_stop = gr.Button("Stop server", variant="stop")

                t4_status = gr.Markdown()
                t4_url = gr.Textbox(label="URL (copy or click below)", interactive=False)
                gr.HTML("<div style='margin:4px 0'><a id='openlink' href='#' target='_blank' style='color:#00e5ff; font-size:1.1em'>Open in browser</a></div>")

                # Simple JS to update the link
                def _update_link(url):
                    if url:
                        return gr.update(value=f"<script>document.getElementById('openlink').href='{url}';</script>Click the link above or paste {url} in your browser")
                    return ""

                server_state = gr.State(None)

                t4_launch.click(
                    fn=launch_browser_player,
                    inputs=[t4_source, t4_local, t4_folder, t4_playlist, t4_cols, t4_mode, t4_pixel, t4_vol, t4_loop, t4_port, workspace, server_state],
                    outputs=[t4_status, t4_url, server_state]
                ).then(_update_link, t4_url, gr.HTML())

                t4_stop.click(stop_server, inputs=[server_state], outputs=[t4_status, server_state])

                gr.Markdown(
                    "**Tip:** After launching, the page at the URL above is the original ASCILINE web player. "
                    "It uses the exact same engine and protocol. Close this Gradio app or click Stop when you're done."
                )

        # Footer note
        gr.Markdown(
            "---\n"
            "All processing re-uses the real `VideoDecoder` + `AsciiMapper` and follows the exact behavior documented in the project. "
            "Outputs are deliberately organized so you (and any AI tools) can find them easily later."
        )

    return demo


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("Starting ASCILINE Studio...")
    print("Make sure you have installed the extra packages: gradio pillow imageio")
    print("The app will open in your browser automatically.")
    demo = build_ui()
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        inbrowser=True,
        show_error=True,
        theme=gr.themes.Soft(),
        css=DARK_CSS,
    )
