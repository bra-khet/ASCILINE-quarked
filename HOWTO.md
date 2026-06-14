# HOWTO: ASCILINE for Complete Beginners (Your Personal AI-First Workspace)

**This is your personal fork (ASCILINE-quarked).**  
The goal of this workspace is to let *you* (and AI assistants like me) deeply understand, experiment with, and build upon a real-time video-to-ASCII rendering system. Everything is intentionally small, readable, and hackable so we can explore applications together — especially the surprising AI/LLM angles the original developer hinted at.

This document assumes **you know nothing** about the project. It uses plain language, short sentences, and concrete steps. Read it once, then use it as a reference while you play with the code.

> **Sprint note for this file**: This HOWTO was created as the first focused sprint to turn the raw fork into a documented, AI-assisted personal lab. All explanations are grounded in the actual code (stream_server.py, ascii_video_player2.py, app.js, codec.*).

---

## 1. What Is ASCILINE, Really? (The One-Sentence Version)

ASCILINE takes a normal video file (like an MP4), shrinks every frame down to a tiny grid of characters (letters, symbols, or colored squares), and sends that tiny grid 24–30 times per second to your browser or terminal so it *looks* like moving video — but it is actually just text and colored dots drawn on an HTML5 canvas or in your command line.

It is **not** a normal video player. There is no `<video>` tag. The browser never decodes H.264. It is JavaScript drawing letters (or 1-pixel blocks) as fast as it receives small data packets over a WebSocket.

---

## 2. Why Does This Exist? (The Vision in Plain Words)

The original README says the core objective is: "transform the web into a highly dynamic and interactive typographic canvas."

Real-world payoffs mentioned:

- You can put **CSS effects** (glows, shadows, animations, filters) directly on the "video" because it is just text on the page.
- It uses very little bandwidth once the server has done the work (great for weak networks or tiny devices).
- It bypasses browser video restrictions and ad-blockers (the page just sees "canvas updates").
- **AI / LLM bridge**: instead of sending heavy images or video clips to an AI vision model, you send a compact *text* representation of the scene. LLMs are extremely good at reading text, so this can be surprisingly "token-efficient."

The project also ships a standalone terminal player (no browser needed).

---

## 3. How the Whole System Actually Works (Step-by-Step, No Magic)

There are two main ways to use it:

A. **Web mode** (the fancy one) — browser + Python server  
B. **Terminal mode** (simple) — just Python printing colored text in your shell

### Web Mode Flow (the main thing)

1. You run `stream_server.py` (or serve.bat) on your computer. This starts:
   - A tiny web server (FastAPI + uvicorn) on http://localhost:8000
   - A WebSocket endpoint at `/ws`
   - An audio streaming endpoint at `/audio`

2. You open that URL in Chrome/Edge/Firefox. You see a styled "blog post" page with a dark player area and a big play button overlay.

3. When you click "Initialize Uplink":
   - The browser JavaScript (app.js + codec.js) opens a WebSocket to the server.
   - The server picks the next video from your queue (folder, playlist, or single file).
   - The server opens the video with OpenCV (`cv2.VideoCapture`).
   - For every frame:
     - It resizes the frame to a small grid you chose (example: 200 columns wide).
     - It converts the resized frame to grayscale to pick ASCII characters (brighter = denser symbol from a fixed 93-character palette).
     - It keeps the original color at low resolution.
     - It packs the result: either plain text (black & white mode) or a tight binary array of [character_code, red, green, blue] per cell.
   - Optional but powerful: the **adaptive codec** (codec.py on server, codec.js in browser) looks at the previous frame and decides:
     - Send the whole thing compressed (zlib), or
     - Send *only the cells that changed* (delta) + zlib, or
     - Send raw if compression would make it bigger.
     - It can also do "lossy" on the color part only (character shape always stays exact). This makes low-motion video absurdly small on the wire.
   - At the same time, the server uses FFmpeg (if volume > 0) to extract and re-encode just the audio track as MP3 and streams it over plain HTTP.

4. The browser receives:
   - An `INIT:...` text message that tells it the grid size, FPS, color mode, whether it's "pixel mode", etc.
   - Then a stream of frame data (text or binary).
   - Separately it loads the audio element.

5. Rendering (the part that feels like video):
   - JavaScript uses `requestAnimationFrame`.
   - It keeps a small jitter buffer of incoming frames.
   - **Master clock is the audio**: `audio.currentTime` tells the renderer exactly where we are in the movie. Video frames are dropped or waited for so picture and sound never drift.
   - For normal color modes it draws on a hidden canvas using `fillText` (one letter at a time, but optimized by skipping color changes). A second invisible `<pre>` layer holds selectable transparent text so you can copy the "video" as text.
   - For `--pixel` mode it uses `putImageData` — each grid cell becomes one screen pixel (stretched by CSS). Looks closer to real low-res video.
   - Status bar shows live FPS, buffer size, and current mode.

Result: 24–30 FPS "video" made entirely of typography or colored blocks, perfectly synced, using kilobytes per second instead of megabytes.

### The Terminal Player (ascii_video_player2.py)

No server, no browser. It does almost the same decode + map steps, but prints ANSI escape codes (`\033[38;2;R;G;BmX`) straight to your terminal using truecolor. Zero flicker because it homes the cursor and overwrites. Great for local scripting or when you just want to watch something in the console.

The two players share the exact same two core classes:
- `VideoDecoder` — opens video, resizes frames, yields (grayscale, color) pairs.
- `AsciiMapper` — turns those into characters + color.

This sharing is intentional and makes the project easy to reuse for pipelines.

---

## 4. Answering Your Specific Questions

### What can I do with this on my GitHub Pages?

GitHub Pages is **static-only** hosting (just files, no running Python).

**The good news**: The entire user interface (index.html + style.css + app.js + codec.js) is pure static client-side code. It is tiny and can live on GitHub Pages perfectly.

**The catch**: Without the Python backend there is no one to:
- Decode videos with OpenCV
- Open the WebSocket and push frames
- Stream the audio

So a pure Pages deployment will show the pretty manifesto page and the player box, but clicking play will just sit there (connection error).

Practical things you *can* do today:
- Publish the styled page itself as documentation or a landing page for your fork.
- Add a big "Run locally" or "Watch the demo on my VPS" button.
- Host the *full stack* (Python + files) somewhere cheap that can run a server (Render.com free tier, Railway, Fly.io, a tiny VPS, even a home Raspberry Pi exposed via Cloudflare Tunnel or ngrok). Then your GitHub Pages site can just link to the live player URL.
- For very short clips (5–15 seconds), you could pre-generate the frame data into a JavaScript array or JSON file and make a fully self-contained single-file demo that plays from memory with no server. Size is manageable because the grids are small. Not practical for full movies.

Bottom line: Great for the *presentation layer* and for linking to live instances. Not a zero-config "upload video, get ASCII page" on Pages alone.

### Is it self-contained in a small performance page?

**Yes for the frontend.**

- index.html is under 85 lines.
- The two JS files together are a few hundred lines of focused code.
- CSS is minimal "blog + player" styling.
- Total transferred size for the page assets is tiny (<30 KB).
- Once connected, the *rendering* is extremely light: the browser is just stamping letters or 1×1 colored rectangles. All the expensive video decoding and character mapping happened on the server using fast Python/NumPy/OpenCV.
- The data that actually travels per frame is tiny thanks to the adaptive codec (often sub-kilobyte for static or low-motion scenes). The README has measured numbers showing 8×–300× wire savings vs sending full frames.

It feels like a high-performance toy because the division of labor is smart: server does the hard perceptual work once, client just draws glyphs.

### How can it be distributed?

Current easiest ways (all work today):

1. **Personal / small team**: `git clone` your fork. `pip install` the four packages. Drop videos in `videos/`. Run the server. Share the localhost URL on your LAN or use `--host 0.0.0.0` + a tunnel.
2. **Public demo**: Run the server on a cloud VM or PaaS that supports Python + long-running processes + WebSocket. Point a nice domain or GitHub Pages link at it. (Remember the anti-ad license clause.)
3. **As a Python library/tool** (very powerful for you):
   - The classes in `ascii_video_player2.py` have almost no dependencies on the web parts.
   - You can `from ascii_video_player2 import VideoDecoder, AsciiMapper` in any script, notebook, or FastAPI app and get a stream of ASCII grids with zero web code.
   - The codec (Python side) is also importable for compression experiments.
4. **Terminal-only distribution**: Just ship the player script + requirements. No HTML at all.
5. **Future packaging ideas** (things we can add later): a single-file HTML that uses the browser's File API + a JS port of the decoder for local files; a PyPI package of just the core mapper; a Docker image.

**License reminder**: MIT plus a specific restriction — you may not use it (or parts of it) to serve unblockable advertisements. The restriction is in the LICENSE file.

### How can I take advantage of this as a video pipeline in various ways?

This is where the project becomes a toolkit rather than "just a player."

Reusable pipeline stages that already exist:

- `VideoDecoder(path, cols, rows)` — gives you consistent resized (gray, bgr) frames at the exact grid you asked for. It even has a `.grab()` fast-skip for high-FPS sources.
- `AsciiMapper` — gives you the character matrix + color matrix, or a ready-to-print ANSI string.
- The frame-packing logic in stream_server (and the codec) turns that into the efficient on-wire format.
- Audio extraction is a separate FFmpeg one-liner you can reuse.

Concrete pipeline examples you can build in one afternoon:

- Batch "ASCII-ify" a folder of clips and save each frame as a small .npy or a folder of .txt files.
- While playing, also write a sidecar JSONL log of "frame 1423: top-left 20% is bright → probably sky" or feed simple stats.
- Real-time effects: after you have the char/color matrices, swap characters, posterize colors, overlay text, before sending or before terminal print.
- Dual output: stream to browser *and* simultaneously write a low-bandwidth "ASCII video" file using the same adaptive encoder.
- Queue system (playlist.json or --folder) already gives you a way to process many videos with per-item settings.

Because the grid is tiny and explicit, many classic video tasks become simple array operations on the character or color planes instead of pixel magic.

### LLM / Token-Efficient Video Ingestion (the part the dev hinted at)

This is the killer application for "AI first" personal work.

Usual way to give video to an LLM:
- Sample frames → turn into base64 JPEGs or let the vision model consume them directly.
- Cost: high token count (images are expensive), high latency, rate limits, and you lose precise timing/structure.

ASCILINE way:
- Server (or your script) reduces the video to a stream of small text grids.
- Each grid cell is one character that a human (and an LLM) can "see" as shape + brightness.
- With color modes you also have per-cell RGB (quantized).
- The entire frame can be represented as a short block of text:
  ```
  Frame 00042:
  `.,:;+!rc*/z?s...
  ....@@%#*...
  ```
  (plus optional color annotations or just the raw bytes if your LLM pipeline can handle binary).

Why this is token-efficient:
- A 240×67 grid is ~16,000 cells. Raw ~16k–64k bytes depending on format.
- After adaptive delta + zlib on real content you are often sending a few hundred bytes to a couple KB per frame on the wire.
- As pure text in a prompt you can be even more compact (drop unchanged regions, use run-length ideas, or just describe deltas in English: "only bottom third changed, now shows a person walking").
- LLMs trained on code and text are shockingly good at "reading" ASCII art for semantics: "there is a bright vertical shape moving left → person", "sudden full-screen bright → explosion or cut", on-screen text that survives the low-res mapping can sometimes be read, etc.
- You stay in the text domain the entire time — no vision model required for many understanding tasks.

Realistic personal projects that become cheap:

- Live or batched "what is happening" summarizer: feed rolling 3–8 second windows of ASCII frames to a local or cheap API LLM and log the descriptions + timestamps. Perfect for long unedited footage.
- Change detection without vision: just watch the size of the delta or the number of cells that changed. Big deltas = action / cut. Use this to decide when to spend money calling a real vision model.
- Cheap indexing / search over a personal video library: store the ASCII streams (they compress extremely well) alongside embeddings of their LLM descriptions.
- On-device always-on analysis: run the decoder + a tiny local LLM (Ollama, llama.cpp) on a laptop or mini-PC. Camera feed → ASCII grid → local model decides "person entered room" or "screen showed a chart" without ever sending pixels anywhere.
- Creative loops: ask an LLM "here is the current ASCII frame, output a new grid that continues the story for the next frame" and pipe the output grid into a renderer. Instant AI-generated typographic animation.
- Accessibility / description for blind users or archives: the text nature makes it easy to combine with TTS.

Honest limits (so you don't over-promise):
- Spatial resolution is deliberately low. Fine details, small faces, and tiny on-screen text are lost or abstracted.
- You chose the fidelity with `--cols`, `--mode`, and `--pixel`. Higher = more CPU on server + more data.
- It is a *semantic / motion / atmosphere* representation, not a preservation codec.
- Best source material is 24–30 fps cinematic content. Very high FPS or shaky cam still works but gets decimated.

Still: for many "understand what is in this video over time" tasks, this is dramatically cheaper than feeding images to vision models.

### Applications Beyond Visual Media Production / Streaming?

Yes — lots. The system is really a **real-time low-resolution structured text renderer + compressor for 2D grids**.

Things that are not "watch a movie":

- **Data visualization as live "video"**: any 2D array that changes over time (simulation grids, cellular automata like the included mandelbrot/life test sources, heatmaps, network traffic matrices, ML activation maps, game boards, sensor arrays) can be fed through the same mapper and watched or streamed. Humans and LLMs can both "see" the patterns.
- **Ultra-low-bandwidth remote state**: instead of sending screenshots or video of a dashboard, send the ASCII version. Copy-pasteable, grep-able in logs, works over terrible connections, survives where video is blocked.
- **Procedural / generative art**: the character palette + color rules become a creative constraint. Combine with code that mutates the grids.
- **Accessibility layer**: turn GUI or game visuals into live text that screen readers or braille displays can consume.
- **Monitoring & alerts**: point a camera (or screen grabber) at something, turn it into ASCII, watch simple statistics (average brightness in a region, number of changed cells). Trigger on thresholds without any ML.
- **Education**: the mapper is basically "quantize brightness to a symbol, quantize color, optional spatial downscale". Perfect for teaching the very first steps of computer vision and signal processing. The whole stack is small enough to read in an afternoon.
- **Terminal UIs and IoT**: the terminal player or a stripped web version works on devices that choke on real video codecs.
- **Archival + search**: an "ASCII video" file (sequence of grids) is searchable and diffable in ways pixels are not. You can literally grep for patterns across years of footage.
- **Hybrid AI pipelines**: ASCII for the cheap always-on pass, expensive vision model only on frames the ASCII layer flagged as interesting.
- **Text-only environments**: intranets, old terminals, email newsletters, plain-text documentation that still wants to convey motion.

Because the output is ultimately just characters + small color info, it composes beautifully with everything that already speaks text (LLMs, shells, version control, search engines, logs).

---

## 5. Beginner Tutorial — Get It Running on Windows (You, Right Now)

### Step 0: Prerequisites
- Windows (PowerShell recommended)
- Python 3.10 or newer (you probably have it; check with `python --version`)
- Git (for cloning/updating your fork)
- (Strongly recommended for audio) FFmpeg: `winget install ffmpeg` then restart your terminal
- A couple of short video files you have the right to use (or we'll make synthetic ones)

### Step 1: Clone and Set Up a Clean Environment (Very Important on Windows)

```powershell
cd C:\Users\robin\claude-code\ASCILINE-quarked
git status          # should say clean
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install fastapi uvicorn opencv-python numpy websockets
```

Activate the venv **every time** you work on this project in a new terminal.

(Why venv? Avoids polluting your global Python and makes sure we always use the project interpreter — important for AI tooling and reproducibility.)

### Step 2: Get Some Video Content

The `videos/` folder has only a `.gitkeep`. Videos are deliberately not committed (see .gitignore).

**Easiest**: copy 1–3 short MP4s you own into the `videos/` folder.

**Or generate the exact test clips the experiments use** (requires FFmpeg):

Open PowerShell in the project folder (after activating venv is fine) and run these four commands:

```powershell
ffmpeg -y -loglevel error -f lavfi -i "testsrc2=size=640x360:rate=30" -f lavfi -i "sine=frequency=440:duration=6" -t 6 -pix_fmt yuv420p videos/test.mp4
ffmpeg -y -loglevel error -f lavfi -i "mandelbrot=size=640x480:rate=24:end_scale=0.3" -t 5 -pix_fmt yuv420p videos/mandel.mp4
ffmpeg -y -loglevel error -f lavfi -i "life=size=320x240:rate=24:mold=10:ratio=0.1:death_color=#101030:life_color=#30ff80" -t 5 -pix_fmt yuv420p videos/life.mp4
ffmpeg -y -loglevel error -f lavfi -i "smptebars=size=640x360:rate=24" -vf "drawtext=text='ASCILINE':fontsize=60:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.5" -t 4 -pix_fmt yuv420p videos/bars.mp4
```

You now have `test.mp4`, `mandel.mp4`, `life.mp4`, `bars.mp4` — perfect for testing every mode.

### Step 3: Start the Server (Web Player)

With venv active:

```powershell
python stream_server.py --folder videos --cols 200 --mode 3 --loop
```

Or the Windows shortcut (it calls bare `python`, which will use the venv python if you activated):

```powershell
.\serve.bat --folder videos --cols 200 --mode 3 --loop
```

You should see a big ASCII logo, the queue of videos, and:

```
🚀 Server live → http://localhost:8000
```

Open that URL.

Click the big circular play button in the center.

You should hear audio (if vol > 0) and see moving ASCII or colored symbols.

Useful flags while experimenting:

- `--cols 160` (smaller = faster, less detail)
- `--cols 280` (more detail, more work for CPU)
- `--mode 1` (pure black & white text, very small)
- `--mode 5 --pixel` (closest to real video — colored blocks)
- `--vol 0` (no audio at all — lighter on CPU)
- `--debug` (live RAW vs WIRE bandwidth numbers in the terminal — watch the compression magic)
- `--loop` (we already used it)

Press Ctrl+C in the server terminal or type `/quit` + Enter to stop.

### Step 4: Try the Terminal Player

```powershell
python ascii_video_player2.py videos/bars.mp4 --cols 100 -q 0
```

(Or `.\play.bat videos/bars.mp4 -c 100 -q 0`)

Watch it in your terminal. Resize the window *before* starting — resizing during playback breaks the layout.

### Step 5: Play With playlist.json (Per-Video Settings)

Edit `playlist.json` (example entries are there with EXAMPLE_ names — change them or create your own).

Then run:

```powershell
python stream_server.py --playlist playlist.json --cols 220 --loop
```

Each entry can have its own `mode`, `pixel`, `vol`, `cols`.

### Step 6: Quick Customization

- Colors & look: edit `style.css` (CSS variables at the top — `--accent-color`, `--bg-color`, etc.).
- The "blog post" text is in `index.html` — you can rewrite the manifesto for your own projects.
- Want different characters? The palette lives in `ascii_video_player2.py` inside `AsciiMapper.DEFAULT_PALETTE`.

---

## 6. Using This for AI Work — Concrete Starting Points

Once you have the server or the classes working, here are tiny experiments you can ask me to help implement:

1. **Frame dumper**: a 20-line script that walks a video and writes every Nth frame as a .txt file of the ASCII grid + a small sidecar for colors. Then feed a folder of those .txt to an LLM.
2. **Live describer bridge**: modify (or wrap) the server so that every 5 seconds it also sends the current grid (or a text summary) to a local Ollama endpoint and logs the reply with timestamp.
3. **Delta-based interestingness**: while decoding, if the number of changed cells (or the delta message size) exceeds a threshold, flag the timestamp. This is a zero-ML "something moved a lot" detector.
4. **Self-contained short demo**: take 8 seconds of one of the test clips, pre-encode the adaptive frames into a JS file, and make a single HTML that plays it with no Python at all. (Great portfolio piece.)
5. **Custom mapper**: subclass or replace AsciiMapper so that certain brightness ranges become emoji or specific symbols for artistic effect.

All of these are natural because the data is already in the most LLM-friendly format possible: structured text grids.

---

## 7. Project Structure (What Each File Actually Does)

- `stream_server.py` — the FastAPI app, queue logic, WebSocket frame pump, audio extraction, CLI parser, interactive /help/status commands.
- `ascii_video_player2.py` — the pure reusable core: `VideoDecoder` + `AsciiMapper` + `TerminalRenderer`. Shared by web server and standalone player.
- `codec.py` + `codec.js` — the adaptive compressor (raw / zlib / delta + optional lossy color). The JS side is the exact decoder the browser uses; tests prove they stay bit-exact.
- `app.js` — browser state machine, WebSocket handling, master-clock A/V sync, canvas + selection-layer rendering, pause/resume.
- `index.html` + `style.css` — the "blog + player" UI. Deliberately minimal.
- `experiments/` — correctness tests (Python encoder vs JS decoder), vector generators. Run them after changes.
- `serve.bat` / `play.bat` — Windows one-liners (consider making explicit .ps1 versions that call `.\.venv\Scripts\python.exe` for extra safety).
- `playlist.json` — example per-video configuration.
- `videos/` — your content (never commit the actual files).
- `HOWTO.md` (this file) — the on-ramp for you and future AI sessions.
- `README.md` — the original project pitch (still useful).

The code is unusually well-commented for a small project. Reading `VideoDecoder` and `AsciiMapper` first will teach you 70% of the "how".

---

## 8. Common Gotchas & Windows Tips

- Always activate the venv before running Python commands.
- FFmpeg must be in PATH for audio (vol > 0). Use `--vol 0` if you don't have it or don't need sound.
- High `--cols` values (500+) on `--mode 5 --pixel` will make the Python side CPU-bound. The server will still send frames but A/V sync can suffer. Lower the number.
- The server prints `[AUTO] 1920x1080 → grid 240x67` — it calculates rows from aspect ratio so nothing gets stretched.
- Source videos > ~35 fps get automatically decimated to ~30 fps on the server (using cheap `grab()` skips).
- Pause in the web player mutes the audio client-side but keeps the server clock running (so resume catches up cleanly).
- Resizing the browser window after start works for layout but the internal canvas grid stays fixed (it was chosen at INIT time).
- On Windows PowerShell, the ANSI colors in the terminal player and server banner work because the scripts do `os.system("")`.
- If you see "FileNotFoundError" for a video, check that the name in playlist/folder matches exactly (case sensitive on some filesystems) and that resolve logic found it.

---

## 9. Next Personal Steps & How to Work With AI on This Repo

1. Get the four synthetic clips running in both web and terminal modes.
2. Watch the bandwidth numbers with `--debug` on a talking-head video vs a high-motion trailer. The difference is educational.
3. Pick one small pipeline experiment (see section 6) and we implement it together.
4. Keep notes in your own `mynotes.txt` (already gitignored) or open issues/PRs in your fork.
5. When you want to change behavior, we will add the exact "BUG FIX" or "CHANGED / WHY" comments required by the project style.

This repo is now set up as a clean, small, extremely legible laboratory for real-time media, compression, and especially text-as-video for AI consumption.

Welcome to your typographic canvas. Let's build interesting things on it.

---

*End of HOWTO. Everything else is in the source files and the original README. Ask me anything about a specific function or "how would I add X for my LLM pipeline?" and we go from here.*
