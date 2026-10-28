# Quran SRT Sync: Audio & Subtitle Synchronizer for Video Editing

**Quran SRT Sync** is a specialized audio-processing and Arabic speech-alignment application that automatically synchronizes Quran subtitles with Quran recitation audio.

It solves the common problem where imported SRT subtitles lag, lead, or drift out of sync in video editing applications due to reciter pauses (waqf), tajweed elongations (madd 2–6 harakat), breath intervals, and variable recitation speeds.

---

## 🌟 Key Features

### 1. Authoritative Arabic Text Preservation
- Reads the supplied Arabic SRT file and **preserves the exact original Quranic text, diacritics (tashkeel), verse order, and formatting verbatim**.
- **Never silently replaces** original Quranic text with speech-to-text predictions.
- Text normalization (removing harakat, unifying alifs, handling phonetic shifts) is used **strictly for acoustic matching and alignment**.

### 2. Multi-Pass Hybrid Alignment Pipeline
- **Acoustic Energy & VAD**: Computes RMS energy envelope to detect speech bursts, voice onset/offset decays, and breath silences (Waqf).
- **Phonetic Speech Recognition**: Extracts acoustic word timestamps using OpenAI Whisper (`tiny`, `base`, `small`, `medium`).
- **Model fallback**: Retries with Whisper Base and then Medium when subtitle words or active speech are missed; larger models take longer and may require additional memory.
- **Best-effort output**: If all available transcripts still miss speech or subtitle words, produces a draft with a prominent warning and highlights affected lines in the web interface (the CLI reports their line numbers). Unmatched words may have interpolated timings. The downloaded SRT remains standard SRT and does not include warning markers.
- **Dynamic Sequence Alignment**: Needleman-Wunsch / sequence alignment with custom Quranic phonetic confusion matrix to map authoritative words to spoken audio segments.
- **Acoustic Boundary Refinement**: Snaps start/end timestamps to true vocal energy onsets and offsets.
- **Editor-Friendly Timing**: Applies pre-roll padding, post-roll linger, minimum subtitle duration, and contiguous timing so adjacent captions have no gaps or overlaps.

### 3. Multiple Synchronization Modes
1. **Preserve Subtitle Segmentation (Default)**:
   - Keeps the exact number, order, and lines of the original SRT.
   - Accurately adjusts only start and end timestamps based on real recitation timing.
2. **Word-Level Synchronization**:
   - Aligns individual Arabic words with spoken timings.
   - Generates one subtitle per word (or configurable groups of words: 1, 2, 3 words).
   - Designed for word-by-word animated and karaoke subtitle presets in video editing applications.
3. **Verse-Level Synchronization**:
   - Aligns entries to recitation verse segments and waqf pauses.

### 4. Reciter Verse Repetition Handling
- Reciters frequently repeat an emotional verse or part of an ayah twice (e.g. during Taraweeh or Mujawwad recitation).
- **Default Behavior (`encompass`)**: When a repetition is detected in the audio, the application **keeps that single verse subtitle on screen for the full duration of both readings** (`start = rendition_1.start`, `end = rendition_2.end`). The subtitle does not disappear or flash during the inter-repetition breath pause.
- Also supports `duplicate` mode (creates separate subtitle entries for each rendition) or `off`.

### 5. Modern Interactive Web Interface & Audio Player
- **Dual Dropzone**: Drag-and-drop MP3, WAV, or M4A audio files and Arabic SRT files.
- **Bulk Synchronization**: Enter server-local MP3 and SRT folder paths to preview numbered matches, process them with per-file progress, and save corrected SRTs directly into the SRT folder's `corrected` subfolder.
- **Live Karaoke Teleprompter**: The active subtitle glows emerald and auto-scrolls in real-time as the recitation plays.
- **Click-to-Seek**: Click any subtitle line to instantly jump playback to that timestamp.
- **Side-by-Side Comparison**: Displays original timing, corrected timing, shift delta ($\Delta t$), and authoritative text.
- **Inline Time Adjustments**: Micro-adjust start/end times right in the table before exporting.
- **One-Click Sample Loader**: Instant demo using Surah Al-Fatihah recited by Mishari Rashid Al-Afasy.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+ (Tested and verified on Python 3.13)
- Installed dependencies:
  ```bash
  pip install torch soundfile scipy numpy openai-whisper fastapi "uvicorn>=0.36" python-multipart
  ```

### Quick Launch (Web Interface)
Double-click `run_app.bat` or run:
```bash
python run_app.py
```
This automatically starts the server and opens your browser at:
`http://127.0.0.1:8000`
On Windows, the launcher uses the selector event loop to avoid noisy connection-reset
tracebacks when the browser closes an audio stream.

For bulk synchronization in the web interface, enter the local MP3 folder and the local
Arabic SRT folder (pre-filled with `<application-folder>\data\arabic_srt`), then select
**Find Matching Files**. The app scans MP3 filenames first
in sorted order and matches each numeric ID to `<number>_arabic.srt` (so `080.mp3` matches
`80_arabic.srt`). Select **Start Bulk Sync** to process each pair in sequence. Corrected
Arabic SRT files are written to an `srt` subfolder inside the MP3 folder, retaining the
matched Arabic SRT filename (for example, `80_arabic.srt`). Notices about SRT files without
a matching MP3 are hidden in the web interface. These paths are local to the computer
running the web server.

---

## 💻 Command Line Interface (CLI)

For batch scripts or headless automated pipelines:

```bash
# Basic synchronization (preserves original SRT lines)
python cli.py --audio recitation.mp3 --srt original.srt --output corrected.srt

# Bulk synchronize numbered MP3 files against matching *_arabic.srt files
python cli.py --audio-dir "C:\Quran\mp3" --srt-dir "C:\Quran\srt" --model small

# Word-by-word karaoke subtitle synchronization
python cli.py -a recitation.mp3 -s original.srt -o word_corrected.srt -m word --words-per-sub 1

# Using Whisper Small model with 50ms pre-roll and 100ms post-roll padding
python cli.py -a audio.mp3 -s sub.srt --model small --start-pad 50 --end-pad 100 --offset 0
```

Bulk mode scans MP3 files in sorted filename order, then finds each matching Arabic SRT by number (for example, `080.mp3` with `80_arabic.srt`). It scans only the two selected directories (not subdirectories) and ignores SRT files without the `_arabic.srt` suffix. Corrected files are written to a `corrected` folder inside the SRT directory, retaining each SRT filename and appending `_corrected` (for example, `80_arabic_corrected.srt`). Missing or ambiguous pairs are reported, while other matched files continue processing.

### CLI Arguments
| Flag | Description | Default |
| :--- | :--- | :--- |
| `-a`, `--audio` | Path to audio file (MP3, WAV, M4A, etc.) for single-file mode | Required in single-file mode |
| `-s`, `--srt` | Path to Arabic SRT file for single-file mode | Required in single-file mode |
| `--audio-dir` | Directory of numbered MP3 files for bulk processing | — |
| `--srt-dir` | Directory of numbered `*_arabic.srt` files for bulk processing | — |
| `-o`, `--output` | Path to output synchronized SRT | `[original-name]_corrected.srt` |
| `-m`, `--mode` | `preserve`, `word`, or `verse` | `preserve` |
| `-w`, `--words-per-sub` | Words per subtitle in `word` mode | `1` |
| `--model` | Whisper model (`tiny`, `base`, `small`, `medium`) | `small` |
| `--offset` | Global timing offset in milliseconds | `0.0` |
| `--start-pad` | Milliseconds to display before voice onset | `60.0` |
| `--end-pad` | Milliseconds to linger after voice offset | `120.0` |
| `--min-dur` | Minimum duration per subtitle in ms | `600.0` |
| `--allow-overlaps`| Disable contiguous timing; allow gaps and overlapping timestamps | `False` |

---

## 📂 Project Architecture

```
quran-srt-sync/
├── core/
│   ├── normalizer.py     # Quranic text normalization & phonetic similarity
│   ├── audio.py          # SoundFile decoding, polyphase resampling, RMS VAD
│   ├── srt_parser.py     # Robust SRT reader/writer with UTF-8 BOM encoding
│   ├── aligner.py        # Multi-pass forced alignment & editor-friendly timing adjustments
│   └── quran_db.py       # Surah metadata & text-based Surah identification
├── static/
│   ├── index.html        # Modern Tailwind dark-mode UI with Amiri typography
│   └── app.js            # Audio player, waveform visualizer & karaoke teleprompter
├── samples/
│   ├── al_fatiha.mp3     # Sample recitation audio (Mishari Rashid Al-Afasy)
│   └── al_fatiha_original.srt # Sample original subtitle with unaligned timings
├── tests/
│   └── test_aligner.py   # Unit test suite
├── app.py                # FastAPI web server
├── cli.py                # Command line interface
├── run_app.py            # Browser launcher
└── run_app.bat           # Windows 1-click launcher
```

---

## 🎬 Video Editor Import Tips
1. **Importing the SRT into your video editor**:
   - Open your video editing project.
   - Go to **Text** &rarr; **Local Captions** (or **Subtitles**) &rarr; **Import**.
   - Select the generated `_corrected.srt` file.
   - The editor places each caption at its SRT timecode.
2. **Word-by-Word Animation**:
   - Export with `--mode word`.
   - Apply text animation presets (e.g., Pop-in, Bounce, or karaoke highlighting) if desired.
   - Because each word has its exact spoken duration, the animation synchronizes with each syllable spoken by the reciter!
