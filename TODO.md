# TODO / Roadmap — ASCILINE-quarked (Personal AI-First Lab)

**Status after Sprint 2 (this file):** We have catalogued the full current capabilities, answered the "other capabilities", transcription, re-encoding, color, formats, and extensibility questions in detail, created a working minimal demo pipeline (`transcribe_ascii.py`), and recorded concrete next steps with difficulty/value estimates. Everything is now in one living list so we (you + AI) can pick ONE narrow item per future exchange.

See also: [HOWTO.md](./HOWTO.md) for beginner explanations and the original [README.md](./README.md).

---

## Current Capabilities (What the Engine Can Do Today, Without New Code)

### Core Reusable Pieces (Best Starting Point for Everything)
- `VideoDecoder(path, cols, rows, skip_gray=False)` from `ascii_video_player2.py`:
  - Works on **any** source `cv2.VideoCapture` can open (file path, webcam index like `0`, some RTSP/HTTP streams, image sequence patterns in some builds).
  - Always resizes to your exact grid while preserving the mapping between gray (for char choice) and color.
  - Exposes `fps`, `frame_count`, original dimensions.
  - `.grab()` for cheap high-FPS skipping (used internally for decimation).
  - `skip_gray=True` optimization for pure pixel mode.
- `AsciiMapper(palette=None, quantize_bits=0)`:
  - Turns any (gray, bgr) pair into characters + color.
  - Fully customizable 93-char (or shorter) palette.
  - Built-in quantize + RLE for the ANSI string path.
  - Internals (`_lut`, `_n`) are accessible for custom pipelines.
- The adaptive **codec** (`codec.py` + `codec.js`):
  - Standalone compressor for any grid data that looks like our frame buffers (char+RGB or raw BGR).
  - RAW / ZLIB / DELTA + optional lossy color tolerance.
  - Produces tiny, round-trippable "ASCILINE video" binary streams (see `experiments/` for generators and verifiers). Can be used for offline storage instead of text or standard video.
- Queue / playlist system in the server (per-video mode, cols, pixel, vol overrides). Works for batch processing too if you reuse the logic.
- FPS decimation, auto row calculation from aspect, debug bandwidth stats.
- Browser player: pure canvas + selectable "video" text layer + CSS hooks + master audio clock sync. No <video> tag.
- Terminal player: zero-flicker ANSI truecolor.

**Other immediate capabilities (no new files):**
- Live webcam → ASCII (terminal or by extending the server): `VideoDecoder(0, cols=160, rows=45)`.
- Any numpy 2D data (simulations, heatmaps, game state, ML features over time) fed to the mapper → "video".
- The web page itself can have extra JS/CSS for effects, overlays, or even feeding the current frame text to a client-side LLM via WebSocket or fetch.
- Pre-generating short self-contained demos (frames baked into JS) for GitHub Pages.
- The codec experiments prove cross-language (py<->js) correctness — any new storage format we invent can be validated the same way.

### Input Formats & Codecs Today
The engine has **no custom demuxer**. Input variety comes entirely from OpenCV 4.x + its FFmpeg backend (confirmed present in this workspace: OpenCV 4.13).

Typical supported containers (most builds):
- .mp4, .m4v, .mov, .mkv, .webm, .avi, .wmv, .flv, .mpg/.mpeg, .ts, some .gif (flaky), image sequences via pattern (e.g. `img_%04d.png` on some platforms).

Common codecs inside those containers:
- H.264 / AVC (most reliable), H.265/HEVC, VP8/VP9, AV1 (if the ffmpeg in the OpenCV build has the decoder), MJPEG, raw YUV, some ProRes, DNxHR, etc.

Audio side (only for the web `/audio` streaming, not needed for pure transcription):
- Whatever FFmpeg can decode from the source; the server always re-encodes the selected track to 128k MP3.

**Live / other sources:**
- Webcams / capture cards via integer index (0, 1, ...).
- Some network streams (RTSP, HTTP MJPEG) if the backend supports.
- Static images: open once, treat as 1-frame "video" (loop it or yield N times).

**What the engine cannot open natively today:**
- DRM / encrypted / browser-only streams (YouTube, Netflix, etc.).
- Some very new or rare containers/codecs without a matching ffmpeg build.
- Direct screen capture (needs extra lib like `mss` + numpy conversion).
- YouTube/HTTP without pre-download.

**How hard to accommodate other file formats / sources?**
- **Zero effort for 95% of cases**: run `ffmpeg -i your_weird_file.ext -c:v libx264 -preset fast -crf 18 -c:a aac normalized.mp4` (one command, excellent quality/size). Then feed the mp4. This is the universal adapter and what almost everyone does.
- Low effort: subclass or wrap `VideoDecoder` to accept a "preprocess" step or support image folders / arrays directly.
- Medium effort: add optional direct ffmpeg subprocess reader (pipe raw frames) or integrate `imageio`, `decord`, or `av` for more exotic cases. Adds deps and complexity.
- For live desktop capture: add `mss` or Windows `dxcam` etc. (small new dep, straightforward numpy path into the existing mapper).
- Verdict in this fork: **Document the ffmpeg pre-transcode path first.** Only add native readers when a specific workflow justifies the dep.

Our internal "codec" (the adaptive grid one) is **not** a standard video codec. It is a domain-specific delta + zlib compressor for low-res char/color grids. You can use it to store "ASCILINE video" files that are far smaller than even heavily compressed pixel video for many sources.

---

## The Questions You Asked — Full Answers + Tradeoffs

### 1. Other capabilities of the engine?
See "Current Capabilities" above. Highlights for "AI first" personal use:
- Turn the video (or any grid data) into a **structured, tiny, text or binary representation** that is trivial to log, diff, search, version-control, or pipe to LLMs / local models.
- Dual outputs while processing (e.g. stream to browser for monitoring + dump sidecar data).
- The selection layer in the browser means you can literally copy-paste the current "frame" as text.
- Because rendering is just text/glyphs, CSS filters, blend modes, and even mixing with other DOM text become possible in ways impossible with real <video>.
- The whole stack (decoder + mapper + codec) is tiny enough to read and modify in one sitting.

### 2. Demo pipeline that turns a clip into "another encoded clip" with ASCILINE content on black/transparent background?
**Yes, and we just built the first version of it.**

See the new `transcribe_ascii.py` (created in this sprint). It supports:
- `--text-out` : transcription to text/structured file (see below).
- `--video-out out.mp4` : re-encodes a standard MP4 whose visual content *is* the ASCILINE representation (colored blocks from the low-res color data, or with char overlays) composited onto a black background (or letterboxed to a viewable size). Uses only existing deps (cv2.VideoWriter + putText for glyphs).
- `--png-sequence outdir/` : writes per-frame PNGs (easy to make transparent BGRA if you want alpha only on the content). Then you can use ffmpeg to mux into any alpha-supporting container (webm/vp9, mov/prores, apng, etc.).

For true "transparent background" final deliverable:
- PNG sequence is the most reliable starting point (no container hassles).
- For a single "encoded clip" file with transparency: webm (VP9/alpha) or MOV + ProRes 4444 are common; the script outputs the frames, you run one ffmpeg command.

This is a **demo pipeline** because it re-uses VideoDecoder + the mapping logic exactly, then materializes the result back into a conventional video file. The "ASCILINE content" is the low-res colored structure (pixel mode) or the glyph decisions + colors.

Future polish (see below): nicer font rendering for the glyph version, variable scale, audio passthrough or re-mixing, using the adaptive codec to store an intermediate "ASCILINE track" before rasterizing.

### 3. Transcribe a video into a text file instead of playing it back?
**Yes — this is one of the highest-leverage things you can do with the engine and is now implemented.**

How it is done (and exactly what `transcribe_ascii.py --text-out` does):
- Open with `VideoDecoder` at your chosen grid (this is the only "resolution" decision — 120–240 cols is typical sweet spot).
- For each frame compute the char matrix (brightness → index into palette).
- Write the characters as a block of lines (one frame per block, separated by a clear marker or just raw for max simplicity).
- Optional: also capture the color matrix at the same resolution (quantized or full) and store alongside.

The script supports:
- Default: chars only (pure UTF-8 text blocks). Extremely LLM- and search-friendly.
- `--format jsonl` or `--include-color`: richer structured output with frame index + text + color data (can be base64-packed or pretty lists; the codec ideas can be reused to delta the color part).
- Same `--cols` / auto-rows logic as the players.
- Progress and metadata header.

You can then:
- `cat thefile.txt | less` or grep it.
- Feed chunks to any LLM (local or API).
- Store in git (text compresses insanely well with the low motion of many sources).
- Build indices, RAG over your video library as text, etc.

### 4. Save color information or strip it away? Applications? Reasons for each?

**Default recommendation in this fork for new work (especially LLM): strip or minimize color first.**

**Reasons to strip / heavily quantize / discard color:**
- The character choice (which of the 93 glyphs) is derived purely from luminance. It carries the large majority of structural, shape, motion, and "what is this scene" information.
- File size / token count: 1 byte per cell (char) vs 3–4 bytes (char+RGB). For a 200×60 grid that's ~12k cells/frame. Over a 2-minute clip the difference is huge for storage and for prompt size.
- Many semantic tasks (action recognition, "is there a person walking", scene changes, rough OCR of large text) work shockingly well from the B&W ASCII alone.
- Simpler data model: one clean 2D char grid per frame. Easier to diff, version, embed, or display in plain terminals/markdown.
- Speed: less data to move around or tokenize.

**Reasons to keep (some) color:**
- Human viewing / re-rendering: the "encoded clip" demo (or the web player in color modes) looks dramatically better with per-cell color. The original vision includes "32K colors", "16M ultra", pixel blocks.
- Color carries semantic signal in many videos: UI elements are color-coded, team jerseys, warning lights, charts, mood (warm/cool), brand, etc.
- Richer LLM prompts: "the bright green rectangle in the upper left just turned red" can be expressed compactly if you keep the color grid (or even just dominant colors per region + the char overlay).
- Artistic / visualization use cases.
- When you plan to pipe the transcribed data *back* into a renderer later (the re-encode pipeline).

**Practical middle grounds (what we should implement next):**
- Always save the clean char grid as text (primary).
- Optional companion "color" layer that is delta-compressed (reuse ideas from `codec.py`) or very low-bit (4–6 bits per channel) or even "per-row run-length of (char, color)".
- For LLM: send chars + a short "color summary" paragraph or a few quantized color patches ("top-left quadrant is mostly cool blue tones").
- Keyframe colors only + deltas for in-between frames (exactly what the adaptive codec already does).

Applications that benefit from color vs not:
- LLM inference / description / RAG / cheap video search: prefer stripped or minimal color.
- Archival "watchable" ASCII video files: keep color.
- Data visualization / scientific: depends on whether hue encodes a variable.
- Re-materialized video clips (the "encoded clip on black"): definitely keep the color data you used for the original mapping.
- Accessibility exports, logs, searchable subtitles + visuals: chars primary + optional sparse color.

The `transcribe_ascii.py` script defaults to the "chars first" philosophy and documents the choice in its help and output header.

### 5. Variety of codecs and file formats usable with the engine? Accommodate others? How hard?
See detailed section above under "Input Formats & Codecs Today".

Summary:
- Input video: broad thanks to OpenCV+FFmpeg. "Almost anything normal" works after a trivial ffmpeg normalize if needed.
- Our "codec": the custom adaptive grid one (excellent for our data; not a drop-in video codec).
- Output today (before this sprint): live WS binary/text, ANSI terminal, in-memory numpy grids.
- New with this sprint: arbitrary text files (various simple formats), standard video containers of the *rendered* ASCII content, PNG sequences (for alpha).
- Audio is only side-loaded via FFmpeg when the web player needs it.

Extensibility cost is low for input (transcode or small wrapper). For new output representations (more structured binary, glTF-style, database rows, etc.) the hard part is deciding the schema — the data is already tiny and explicit.

---

## Prioritized TODO List (Pick ONE per exchange)

### Just Completed (Sprint 2)
- [x] Cataloged all capabilities, formats, color decisions, transcription + re-encode possibilities.
- [x] Created `transcribe_ascii.py` — working demo pipeline for text transcription (default chars-only for LLM use) + basic re-encoded video clip (ASCILINE content on black) + PNG sequence path. Fully answers the "how would that be done" questions with runnable code.
- [x] Created this TODO.md as the single source of truth for the list and decisions.

### Recommended Next (Narrow, High Value, One Sprint Scope)
1. **Polish & expand the transcription pipeline into a proper "ASCII video archive" tool**
   - Add proper structured output formats (e.g. a header + frame blocks or the exact binary frame format from the codec for maximum compactness).
   - Optional: use `codec.py` to delta-compress the color layer when `--include-color`.
   - Nice CLI (progress bars? `tqdm` optional), support for playlists/folders in batch mode, sidecar .meta.json with grid size + palette + fps.
   - Document example LLM usage: "feed first 10 frames + last 10 frames of each minute to local model and log summaries".
   - Difficulty: low-medium. Value: very high for your stated LLM / token-efficient ingestion goal.

2. **Full "re-encode to pretty glyph video" demo (the visual "encoded clip on black/transparent")**
   - Improve the rasterizer in `transcribe_ascii.py` (or a separate `render_ascii_video.py`): use a better way to draw the actual characters (Pillow + a bundled or system monospace TTF for real glyphs, or pre-render a char atlas).
   - Support variable output scale, letterboxing/pillarbox to standard resolutions (720p, 1080p canvas with the tiny grid centered or scaled).
   - Optional audio re-encode/mix from original (using ffmpeg).
   - Transparent path via PNG seq + ffmpeg to alpha webm/mov.
   - Difficulty: medium (font handling + polish). Value: high for "what can I actually watch as a normal video file".

3. **Live / real-time sources and "any grid" input**
   - Make `VideoDecoder` (or a new thin `FrameSource`) accept live camera, and also plain numpy arrays / generators so simulations etc. "just work".
   - Example script: webcam → ASCII terminal with on-screen stats, or webcam → local LLM every N seconds.
   - Difficulty: low. Value: opens "beyond file-based video" immediately.

4. **Compact "ASCILINE .asv" file format + player**
   - Use the existing adaptive codec to write a single binary file (manifest + sequence of encoded frames).
   - A tiny pure-Python (or JS) player that can seek/play the compact file without re-decoding original video.
   - Bonus: delta color only when saving.
   - Difficulty: medium (format design + seeking). Value: excellent for efficient local storage and "token-efficient" archives.

5. **Input format convenience layer**
   - Helper that auto-runs ffmpeg normalize for unknown extensions, or accepts YouTube URLs (via yt-dlp if installed) and downloads to temp.
   - Or direct support for image sequences / folders of stills as a "video".
   - Difficulty: low-medium. Value: removes friction for "accommodate other file formats".

6. **Web player recording / export buttons**
   - Add UI in `app.js` + a backend endpoint to "record this playback as [text dump | compact binary | rasterized video]".
   - Or use MediaRecorder on the canvas for quick "what you see is what you get" MP4 from the browser.
   - Difficulty: low (frontend) to medium. Value: makes the localhost player more of a tool than just a viewer.

7. **Other ideas (lower priority for now)**
   - Custom palettes per video or "themed" mappers (Matrix green, etc.).
   - LLM feedback loop: LLM proposes a modified char grid for the next frame → render it (generative ASCII video).
   - Better A/V sync or variable rate in transcription tools.
   - Packaging (pyproject.toml entry point for the transcribe script).
   - Tests for any new pipeline code (reuse the existing check_vectors pattern).
   - Docker / one-click server + examples.
   - Explore non-video grids (e.g. feed cellular automata state or spectrograms).

---

## Recent fixes (post-Sprint 2)
- Path resolution in gradio_app.py: fixed crash in Tab 1 (transcribe_for_llm) when using default relative workspace + WINDOWS_ROOT absolute (from .windows_cwd.txt); centralized resolver so *all* tabs (incl. the working Tab 3 ASCILINE Clips) + browser player service + open-folder use identical anchoring/fallback and never conflict on relative vs absolute job dirs. (See BUG FIX comments in gradio_app.py.)

## How to Work This List (Sprint Discipline Reminder)
- State a **one-sentence sprint contract** at the start of the exchange naming the *exact* scope.
- Do **one** well-defined item (or sub-item) per exchange.
- Use the `CHANGED / WHY` (or language-appropriate) annotation on every non-trivial edit.
- After the change, suggest or perform `git commit -m "Sprint: <brief>"`.
- Update this TODO.md (mark done, add notes) as part of the work.
- Prefer the simplest solution that answers the goal. Add new abstractions only when the current task actually needs them.
- When in doubt about priority, the LLM / token-efficient / personal archive angle (items 1 and 4) is the strongest "AI first" fit for this fork.

Next user message can simply say: "Sprint: implement item #1 (polish the transcription tool with codec color compression and JSONL + example LLM usage)" or pick any other.

This file + the new `transcribe_ascii.py` + the previous HOWTO now give us a complete on-ramp for exploring every possibility you asked about.

---

*Generated during Sprint 2. Keep this file updated after every exchange.*
