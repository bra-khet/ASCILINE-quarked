#!/usr/bin/env python3
"""
transcribe_ascii.py — Minimal demo pipeline for ASCILINE (Sprint 2 deliverable)

This script and other additions in the ASCILINE-quarked fork are subject to exactly the same license terms as the original project (see the root LICENSE file). This includes the full MIT terms PLUS the strict ANTI-ADVERTISEMENT RESTRICTION: no use (in whole or part) for serving, delivering, or displaying ads, sponsored content, or commercial marketing. Any such use terminates the license immediately.

Intended for personal exploration, creativity, research, accessibility, and low-bandwidth applications only. Zero liability for misuse.
"""

Turns any video that OpenCV can open into:
  1. A plain or structured TEXT FILE of the ASCILINE representation
     (default: clean character grids only — ideal for LLM inference, search, archiving).
  2. A standard "encoded clip" MP4 whose visual content IS the ASCILINE data
     (low-res colored blocks / pixel representation placed on a black background).
  3. A folder of PNG frames (easy path to transparent-background final deliverables via ffmpeg).

This directly answers:
- "Is it possible to transcribe a video into a text file instead of playing it back?"
- "Create some kind of demo pipeline that turns a clip into another encoded clip,
  but encoded with the ASCILINE content on a black/transparent background?"
- Color vs. no-color decisions, why, and how to choose.
- How the engine's input variety works and why ffmpeg pre-transcode is the universal adapter.

Run with the project venv:
    .\.venv\Scripts\Activate.ps1
    python transcribe_ascii.py input.mp4 --cols 160 --text-out clip.asc.txt
    python transcribe_ascii.py input.mp4 --cols 160 --video-out clip_ascii.mp4 --scale 6
    python transcribe_ascii.py input.mp4 --png-sequence frames/

See TODO.md for the full catalog of capabilities, other pipeline ideas, format extensibility,
and the prioritized list. See HOWTO.md for beginner context.

No new dependencies beyond what the rest of ASCILINE already requires
(opencv-python + numpy). The adaptive codec (codec.py) is *not* used here yet
but is noted as the obvious next step for compact color storage.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

# Reuse the battle-tested core (no duplication of video opening / resize logic)
from ascii_video_player2 import VideoDecoder, AsciiMapper


# =============================================================================
# CHANGED: New top-level demo script created in Sprint 2.
# WHY: User explicitly requested (a) a working transcription-to-text pipeline,
# (b) a demo that produces "another encoded clip" of the ASCILINE content on
# black/transparent bg, (c) discussion of color tradeoffs + applications, and
# (d) a decision framework + TODO list. This script + the accompanying TODO.md
# deliver all of that in the simplest possible form using only existing modules.
# The script deliberately defaults to *chars only* (color stripped) because that
# is the highest-leverage starting point for the LLM / token-efficient use case
# that motivated the original dev's comments. Everything else is opt-in.
# =============================================================================


def get_char_matrix(gray: np.ndarray, mapper: AsciiMapper) -> np.ndarray:
    """Replicate the brightness → character selection (same math as AsciiMapper.convert)."""
    indices = np.floor_divide(gray, max(1, 256 // mapper._n))
    np.clip(indices, 0, mapper._n - 1, out=indices)
    return mapper._lut[indices]


def get_color_matrix(bgr: np.ndarray, quantize_bits: int = 0) -> np.ndarray:
    """Return RGB (not BGR) color grid, optionally quantized like the mapper does."""
    rgb = bgr[:, :, ::-1].copy()
    if quantize_bits > 0:
        qb = quantize_bits
        rgb = (rgb >> qb) << qb
    return rgb


def write_text_transcript(
    decoder: VideoDecoder,
    mapper: AsciiMapper,
    out_path: Path,
    include_color: bool = False,
    color_quantize: int = 3,
    format: str = "blocks",
):
    """
    Write the ASCILINE transcription.

    Default (include_color=False): pure UTF-8 character blocks. One frame looks like:

        === FRAME 00042 (t=1.75s) ===
        `.,:;+!rc*/z
        ....@@%#*...
        ...

    This is the recommended form for LLM ingestion, grep, git, RAG, etc.

    With include_color: produces JSONL (one object per frame) containing the
    character block + a colors array (or you can extend to use the adaptive codec
    for delta color later).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = decoder.frame_count or 0
    fps = decoder.fps or 24.0

    if format == "blocks" and not include_color:
        # Purest, smallest, most LLM-friendly form
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# ASCILINE TEXT TRANSCRIPT\n")
            f.write(f"# source_fps={fps:.3f}  grid={decoder._size[0]}x{decoder._size[1]}\n")
            f.write(f"# palette_size={mapper._n}  color=stripped (recommended for LLM)\n")
            f.write(f"# Use: chars carry structure; add --include-color only if you need hue later.\n\n")

            for frame_idx, (gray, bgr) in enumerate(decoder):
                chars = get_char_matrix(gray, mapper)
                lines = ["".join(row) for row in chars]
                block = "\n".join(lines)

                t = frame_idx / fps
                f.write(f"=== FRAME {frame_idx:05d} (t={t:.2f}s) ===\n")
                f.write(block)
                f.write("\n\n")

                if frame_idx % 30 == 0:
                    print(f"  transcribed {frame_idx}/{total or '?'} frames...", end="\r")

    else:
        # Structured JSONL (easy to parse, still very compact)
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            meta = {
                "format": "jsonl",
                "source_fps": fps,
                "cols": decoder._size[0],
                "rows": decoder._size[1],
                "color_included": include_color,
                "color_quantize_bits": color_quantize if include_color else None,
                "note": "Default to chars only for LLM use. Color is optional and can be delta-compressed later with codec.py.",
            }
            f.write(json.dumps({"meta": meta}) + "\n")

            for frame_idx, (gray, bgr) in enumerate(decoder):
                chars = get_char_matrix(gray, mapper)
                text_block = "\n".join("".join(row) for row in chars)

                rec = {
                    "frame": frame_idx,
                    "t": round(frame_idx / fps, 3),
                    "text": text_block,
                }
                if include_color:
                    rgb = get_color_matrix(bgr, color_quantize)
                    # Store as flat list for compactness: [r0,g0,b0, r1,g1,b1, ...]
                    rec["colors"] = rgb.reshape(-1).tolist()

                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

                if frame_idx % 30 == 0:
                    print(f"  transcribed {frame_idx}/{total or '?'} frames...", end="\r")

    print(f"\nWrote transcript: {out_path}  ({out_path.stat().st_size / 1024:.1f} KiB)")


def render_ascii_video(
    decoder: VideoDecoder,
    mapper: AsciiMapper,
    out_video: Path,
    scale: int = 6,
    use_glyphs: bool = True,
):
    """
    Demo "encoded clip": produce a normal MP4 file whose pixels show the ASCILINE
    representation on a pure black background.

    - Uses the low-res BGR directly for the "pixel mode" colored blocks (always correct).
    - When use_glyphs=True, also draws the chosen ASCII character on top using cv2.putText
      (Hershey font — limited but works for demo; no external TTF required).
    - Output size = grid * scale. Black letterbox/pillarbox is automatic.

    This is the simplest possible "turn the clip into another encoded clip with
    ASCILINE content on black background". For prettier typography or true alpha,
    see the PNG sequence path + TODO item #2.
    """
    out_video = Path(out_video)
    out_video.parent.mkdir(parents=True, exist_ok=True)

    cols, rows = decoder._size
    out_w = cols * scale
    out_h = rows * scale

    # mp4v is the most portable fourcc for .mp4 without extra codecs on the target machine
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_video), fourcc, decoder.fps or 24.0, (out_w, out_h))

    if not writer.isOpened():
        raise RuntimeError("Failed to open VideoWriter. Try a different fourcc or install codecs.")

    font = cv2.FONT_HERSHEY_PLAIN
    font_scale = max(0.4, (scale / 8.0))  # rough fit for the cell
    thickness = max(1, scale // 5)

    print(f"Rendering ASCILINE video @ {out_w}x{out_h} (scale={scale}) ...")

    for frame_idx, (gray, bgr) in enumerate(decoder):
        # Base: black canvas at output resolution
        frame = np.zeros((out_h, out_w, 3), dtype=np.uint8)

        # The "ASCILINE content" — low-res color data (this is exactly what pixel mode uses)
        # Nearest-neighbor upscale so each original low-res pixel becomes a solid block
        upscaled = cv2.resize(bgr, (out_w, out_h), interpolation=cv2.INTER_NEAREST)

        if not use_glyphs:
            frame[:] = upscaled
        else:
            # Draw colored blocks + overlay the actual character (classic ASCII look)
            char_grid = get_char_matrix(gray, mapper)
            rgb_grid = get_color_matrix(bgr, quantize_bits=0)  # full color for drawing

            cell_h = scale
            cell_w = scale

            for r in range(rows):
                for c in range(cols):
                    y0 = r * cell_h
                    x0 = c * cell_w
                    color = tuple(int(x) for x in rgb_grid[r, c])  # RGB already
                    # Solid block (the "pixel" content)
                    cv2.rectangle(frame, (x0, y0), (x0 + cell_w - 1, y0 + cell_h - 1), color, -1)

                    # Glyph on top (white or dark depending on brightness for contrast)
                    ch = str(char_grid[r, c])
                    # Very rough contrast decision
                    lum = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
                    txt_color = (0, 0, 0) if lum > 140 else (255, 255, 255)

                    # Center the char inside the cell (Hershey baseline is bottom-left)
                    (tw, th), _ = cv2.getTextSize(ch, font, font_scale, thickness)
                    tx = x0 + (cell_w - tw) // 2
                    ty = y0 + (cell_h + th) // 2
                    cv2.putText(frame, ch, (tx, ty), font, font_scale, txt_color, thickness, cv2.LINE_AA)

        writer.write(frame)

        if frame_idx % 15 == 0:
            print(f"  rendered {frame_idx} frames...", end="\r")

    writer.release()
    print(f"\nWrote ASCILINE-encoded clip: {out_video}  ({out_video.stat().st_size / 1024:.1f} KiB)")


def write_png_sequence(
    decoder: VideoDecoder,
    mapper: AsciiMapper,
    out_dir: Path,
    scale: int = 4,
    transparent: bool = False,
):
    """
    Write per-frame PNGs. Easiest route to "transparent background".

    - With transparent=True we produce BGRA PNGs (alpha = 255 on content, 0 on pure black).
    - Then the user can do:
        ffmpeg -framerate 24 -i frames/frame_%05d.png -c:v libvpx-vp9 -pix_fmt yuva420p out.webm
      or similar for other alpha-capable formats.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cols, rows = decoder._size
    out_w = cols * scale
    out_h = rows * scale

    print(f"Writing PNG sequence to {out_dir}/ ...")

    for frame_idx, (gray, bgr) in enumerate(decoder):
        if transparent:
            # BGRA, black is fully transparent
            canvas = np.zeros((out_h, out_w, 4), dtype=np.uint8)
            upscaled = cv2.resize(bgr, (out_w, out_h), interpolation=cv2.INTER_NEAREST)
            # Convert BGR->BGRA and set alpha where not pure black
            canvas[:, :, :3] = upscaled
            # Simple mask: any non-zero channel means content
            mask = (upscaled > 0).any(axis=2).astype(np.uint8) * 255
            canvas[:, :, 3] = mask
            fname = out_dir / f"frame_{frame_idx:05d}.png"
            cv2.imwrite(str(fname), canvas)
        else:
            canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)
            upscaled = cv2.resize(bgr, (out_w, out_h), interpolation=cv2.INTER_NEAREST)
            canvas[:] = upscaled
            fname = out_dir / f"frame_{frame_idx:05d}.png"
            cv2.imwrite(str(fname), canvas)

        if frame_idx % 20 == 0:
            print(f"  wrote {frame_idx} pngs...", end="\r")

    print(f"\nWrote PNG sequence to {out_dir}/")


def main():
    parser = argparse.ArgumentParser(
        description="ASCILINE transcription & re-encoding demo pipeline. "
                    "Defaults to color-stripped character grids (best for LLMs). "
                    "See --help for color and video re-encode options."
    )
    parser.add_argument("video", help="Input video (anything cv2.VideoCapture can open; use ffmpeg to normalize exotic files first)")
    parser.add_argument("--cols", type=int, default=160, help="Grid columns (default 160; rows auto from aspect)")
    parser.add_argument("--rows", type=int, default=0, help="Grid rows (0 = auto)")

    # Transcription (text) options
    parser.add_argument("--text-out", metavar="FILE", help="Write ASCII transcription to this file")
    parser.add_argument("--format", choices=["blocks", "jsonl"], default="blocks",
                        help="Text output style (blocks = human/grep friendly; jsonl = machine parseable)")
    parser.add_argument("--include-color", action="store_true",
                        help="Include per-cell color in the transcript (increases size a lot; only use when you need hue)")
    parser.add_argument("--color-quantize", type=int, default=3, help="Bits to drop for color when --include-color (default 3)")

    # Re-encode "encoded clip" options
    parser.add_argument("--video-out", metavar="FILE", help="Write a standard MP4 whose pixels ARE the ASCILINE content on black")
    parser.add_argument("--scale", type=int, default=6, help="Upscale factor for video/PNG output (default 6)")
    parser.add_argument("--no-glyphs", action="store_true",
                        help="For --video-out: draw only solid colored blocks (pixel mode look) instead of trying to overlay characters")

    # Transparent / sequence
    parser.add_argument("--png-sequence", metavar="DIR", help="Write individual PNG frames (use with --transparent for alpha)")
    parser.add_argument("--transparent", action="store_true", help="Produce BGRA PNGs with black as transparent (for --png-sequence)")

    args = parser.parse_args()

    if not any([args.text_out, args.video_out, args.png_sequence]):
        parser.error("Nothing to do. Specify at least one of --text-out, --video-out, or --png-sequence")

    print(f"Opening {args.video} ...")
    try:
        decoder = VideoDecoder(args.video, args.cols, args.rows or 0)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Grid: {decoder._size[0]}x{decoder._size[1]}  source_fps={decoder.fps:.2f}  frames~{decoder.frame_count}")

    mapper = AsciiMapper(quantize_bits=0)  # full color quality for any drawing we do; the transcript decides color policy

    # 1. Text transcription (the "transcribe to text file" path)
    if args.text_out:
        print("Transcribing to text (color stripped by default)...")
        write_text_transcript(
            decoder,
            mapper,
            Path(args.text_out),
            include_color=args.include_color,
            color_quantize=args.color_quantize,
            format=args.format,
        )
        # Decoder is exhausted; reopen for subsequent outputs
        decoder = VideoDecoder(args.video, args.cols, args.rows or 0)

    # 2. Standard video clip with ASCILINE content on black
    if args.video_out:
        print("Rendering ASCILINE content as video on black background...")
        render_ascii_video(
            decoder,
            mapper,
            Path(args.video_out),
            scale=args.scale,
            use_glyphs=not args.no_glyphs,
        )
        decoder = VideoDecoder(args.video, args.cols, args.rows or 0)

    # 3. PNG sequence (best for transparent workflows)
    if args.png_sequence:
        print("Writing PNG sequence...")
        write_png_sequence(
            decoder,
            mapper,
            Path(args.png_sequence),
            scale=args.scale,
            transparent=args.transparent,
        )

    print("\nDone. See TODO.md for what to build next (compact binary using codec.py, prettier glyph rendering, LLM usage examples, etc.).")


if __name__ == "__main__":
    main()
