"""
Quran SRT Sync - Web Application Server (FastAPI)
Provides modern REST API & Interactive Web Interface for Quran subtitle synchronization.
"""

import os
import sys
import uuid
import shutil
import numpy as np
from html import escape
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

# Ensure core imports work
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from core.srt_parser import read_srt_file, write_srt_file, parse_srt_content, generate_srt_string, sec_to_time_str
from core.aligner import QuranAligner
from core.bulk import pair_bulk_files
from core.quran_db import detect_surah_from_text
from core.audio import load_and_resample_audio, compute_energy_envelope

app = FastAPI(
    title="Quran SRT Sync",
    description="Synchronizes Quran subtitles with recitation audio for video editing",
    version="1.0.0"
)

# Upload and temporary storage
UPLOAD_DIR = os.path.join(CURRENT_DIR, "uploads")
STATIC_DIR = os.path.join(CURRENT_DIR, "static")
SAMPLES_DIR = os.path.join(CURRENT_DIR, "samples")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Mount static assets
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# In-memory session store
SESSIONS = {}


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_file):
        raise HTTPException(status_code=404, detail="UI index.html not found.")
    with open(index_file, "r", encoding="utf-8") as f:
        content = f.read()
    default_srt_dir = escape(os.path.join(CURRENT_DIR, "data", "arabic_srt"), quote=True)
    return content.replace("__DEFAULT_ARABIC_SRT_DIR__", default_srt_dir)


@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    favicon_file = os.path.join(STATIC_DIR, "favicon.svg")
    if not os.path.exists(favicon_file):
        raise HTTPException(status_code=404, detail="Favicon not found.")
    return FileResponse(favicon_file, media_type="image/svg+xml")


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "Quran SRT Sync", "version": "1.0.0"}


@app.get("/api/audio/{filename}")
async def stream_audio(filename: str):
    """Streams audio file for HTML5 playback."""
    # Check upload dir first, then samples dir
    path1 = os.path.join(UPLOAD_DIR, filename)
    path2 = os.path.join(SAMPLES_DIR, filename)

    audio_path = path1 if os.path.exists(path1) else path2
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="Audio file not found")

    return FileResponse(audio_path, media_type="audio/mpeg")


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    """Downloads synchronized SRT file."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Requested file not found")

    return FileResponse(
        file_path,
        media_type="application/x-subrip",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.get("/api/load-sample")
async def load_sample():
    """Loads bundled Al-Fatiha sample for instant one-click testing."""
    sample_mp3 = os.path.join(SAMPLES_DIR, "al_fatiha.mp3")
    sample_srt = os.path.join(SAMPLES_DIR, "al_fatiha_original.srt")

    if not os.path.exists(sample_mp3) or not os.path.exists(sample_srt):
        raise HTTPException(status_code=404, detail="Sample files not found on disk")

    session_id = str(uuid.uuid4())
    audio_copy_name = f"{session_id}_sample.mp3"
    audio_copy_path = os.path.join(UPLOAD_DIR, audio_copy_name)
    shutil.copyfile(sample_mp3, audio_copy_path)

    entries = read_srt_file(sample_srt)
    all_text = " ".join(e['text'] for e in entries)
    surah_info = detect_surah_from_text(all_text)

    # Compute quick waveform envelope
    audio_16k, duration, _ = load_and_resample_audio(audio_copy_path, target_sr=16000)
    rms, hop_sec = compute_energy_envelope(audio_16k, frame_ms=100.0, hop_ms=100.0)
    # Downsample waveform to ~100 peaks for smooth UI visualization
    peaks = [float(np.round(p, 4)) for p in rms]
    step = max(1, len(peaks) // 100)
    waveform_summary = peaks[::step][:100]

    SESSIONS[session_id] = {
        'audio_path': audio_copy_path,
        'audio_filename': audio_copy_name,
        'entries': entries,
        'surah_info': surah_info,
        'duration': duration
    }

    return {
        "status": "success",
        "session_id": session_id,
        "audio_url": f"/api/audio/{audio_copy_name}",
        "audio_filename": "al_fatiha.mp3",
        "audio_duration": round(duration, 2),
        "waveform": waveform_summary,
        "entries": entries,
        "total_subtitles": len(entries),
        "surah_info": surah_info
    }


@app.post("/api/upload")
async def upload_files(
    audio_file: UploadFile = File(...),
    srt_file: UploadFile = File(...)
):
    """Handles audio & SRT uploads and returns previews."""
    session_id = str(uuid.uuid4())
    
    # Save audio file
    audio_ext = os.path.splitext(audio_file.filename)[1].lower() or ".mp3"
    audio_filename = f"{session_id}_audio{audio_ext}"
    audio_path = os.path.join(UPLOAD_DIR, audio_filename)

    with open(audio_path, "wb") as f:
        content = await audio_file.read()
        f.write(content)

    # Read SRT file content
    srt_bytes = await srt_file.read()
    # Decode with fallback encodings
    srt_text = None
    for enc in ['utf-8-sig', 'utf-8', 'cp1256', 'iso-8859-6', 'latin-1']:
        try:
            srt_text = srt_bytes.decode(enc)
            if any('\u0600' <= c <= '\u06FF' for c in srt_text):
                break
        except Exception:
            continue

    if srt_text is None:
        srt_text = srt_bytes.decode('utf-8', errors='replace')

    entries = parse_srt_content(srt_text)
    if not entries:
        raise HTTPException(status_code=400, detail="Could not find valid SRT subtitle entries in the uploaded file.")

    # Process audio duration & waveform
    try:
        audio_16k, duration, _ = load_and_resample_audio(audio_path, target_sr=16000)
        rms, hop_sec = compute_energy_envelope(audio_16k, frame_ms=100.0, hop_ms=100.0)
        peaks = [float(np.round(p, 4)) for p in rms]
        step = max(1, len(peaks) // 100)
        waveform_summary = peaks[::step][:100]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Audio processing failed: {str(e)}")

    all_text = " ".join(e['text'] for e in entries)
    surah_info = detect_surah_from_text(all_text)

    SESSIONS[session_id] = {
        'audio_path': audio_path,
        'audio_filename': audio_filename,
        'entries': entries,
        'surah_info': surah_info,
        'duration': duration,
        'orig_srt_filename': srt_file.filename
    }

    return {
        "status": "success",
        "session_id": session_id,
        "audio_url": f"/api/audio/{audio_filename}",
        "audio_filename": audio_file.filename,
        "audio_duration": round(duration, 2),
        "waveform": waveform_summary,
        "entries": entries,
        "total_subtitles": len(entries),
        "surah_info": surah_info
    }


class SyncRequest(BaseModel):
    session_id: str
    mode: str = "preserve"              # 'preserve', 'word', 'verse'
    words_per_sub: int = 1
    whisper_model: str = "small"        # 'tiny', 'base', 'small'
    global_offset_ms: float = 0.0
    start_padding_ms: float = 60.0
    end_padding_ms: float = 120.0
    min_duration_ms: float = 600.0
    prevent_overlaps: bool = True
    repetition_mode: str = "encompass"   # 'encompass' (default), 'duplicate', 'off'


class BulkDirectoriesRequest(BaseModel):
    audio_dir: str
    srt_dir: str


class BulkPairSyncRequest(SyncRequest):
    session_id: str | None = None
    audio_dir: str
    srt_dir: str
    audio_filename: str
    srt_filename: str


@app.post("/api/bulk/pairs")
def preview_bulk_pairs(req: BulkDirectoriesRequest):
    """Previews numbered MP3 and *_arabic.srt pairs from local directories."""
    try:
        pairing = pair_bulk_files(req.audio_dir, req.srt_dir)
    except (NotADirectoryError, OSError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return {
        "matches": [
            {"audio_filename": audio.name, "srt_filename": subtitle.name}
            for audio, subtitle in pairing.matches
        ],
        "issues": pairing.errors,
        "output_dir": os.path.join(os.path.abspath(req.audio_dir), "srt")
    }


@app.post("/api/bulk/synchronize")
def synchronize_bulk_pair(req: BulkPairSyncRequest):
    """Synchronizes one verified pair and writes the Arabic SRT to the audio directory's srt folder."""
    try:
        pairing = pair_bulk_files(req.audio_dir, req.srt_dir)
    except (NotADirectoryError, OSError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    pair = next(
        (
            (audio, subtitle)
            for audio, subtitle in pairing.matches
            if audio.name == req.audio_filename and subtitle.name == req.srt_filename
        ),
        None
    )
    if pair is None:
        raise HTTPException(status_code=400, detail="The selected audio and SRT are not a valid numbered pair.")

    audio_path, srt_path = pair
    try:
        entries = read_srt_file(str(srt_path))
        if not entries:
            raise ValueError(f"No valid subtitle entries found in {srt_path.name}")
        result = QuranAligner(whisper_model_name=req.whisper_model).synchronize(
            audio_path=str(audio_path),
            srt_entries=entries,
            mode=req.mode,
            words_per_sub=req.words_per_sub,
            global_offset_ms=req.global_offset_ms,
            start_padding_ms=req.start_padding_ms,
            end_padding_ms=req.end_padding_ms,
            min_duration_ms=req.min_duration_ms,
            prevent_overlaps=req.prevent_overlaps,
            repetition_mode=req.repetition_mode
        )
        output_dir = os.path.join(os.path.abspath(req.audio_dir), "srt")
        os.makedirs(output_dir, exist_ok=True)
        output_filename = f"{srt_path.stem}.srt"
        output_path = os.path.join(output_dir, output_filename)
        write_srt_file(output_path, result['synced_entries'])
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to synchronize {srt_path.name}: {error}"
        ) from error

    return {
        "status": "success",
        "audio_filename": audio_path.name,
        "srt_filename": srt_path.name,
        "output_filename": output_filename,
        "output_path": output_path,
        "stats": result['stats']
    }


@app.post("/api/synchronize")
async def synchronize_subtitles(req: SyncRequest):
    """Runs forced alignment and generates corrected timestamps."""
    session = SESSIONS.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session expired or not found. Please upload files again.")

    audio_path = session['audio_path']
    entries = session['entries']

    aligner = QuranAligner(whisper_model_name=req.whisper_model)

    try:
        result = aligner.synchronize(
            audio_path=audio_path,
            srt_entries=entries,
            mode=req.mode,
            words_per_sub=req.words_per_sub,
            global_offset_ms=req.global_offset_ms,
            start_padding_ms=req.start_padding_ms,
            end_padding_ms=req.end_padding_ms,
            min_duration_ms=req.min_duration_ms,
            prevent_overlaps=req.prevent_overlaps,
            repetition_mode=req.repetition_mode
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Synchronization failed: {str(e)}")

    synced_entries = result['synced_entries']
    stats = result['stats']

    # Generate output SRT file
    orig_name = session.get('orig_srt_filename', 'quran_subtitles.srt')
    base_name, _ = os.path.splitext(orig_name)
    out_filename = f"{base_name}_corrected.srt"
    out_path = os.path.join(UPLOAD_DIR, f"{req.session_id}_{out_filename}")
    write_srt_file(out_path, synced_entries)

    session['synced_entries'] = synced_entries
    session['out_filename'] = f"{req.session_id}_{out_filename}"
    session['download_name'] = out_filename

    return {
        "status": "success",
        "synced_entries": synced_entries,
        "stats": stats,
        "vad_info": result['vad_info'],
        "download_url": f"/api/download/{req.session_id}_{out_filename}",
        "download_filename": out_filename
    }


class SaveEditsRequest(BaseModel):
    session_id: str
    entries: list[dict]


@app.post("/api/save-edits")
async def save_manual_edits(req: SaveEditsRequest):
    """Saves user manual adjustments from the interactive table into the SRT."""
    session = SESSIONS.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    out_filename = session.get('out_filename', f"{req.session_id}_edited.srt")
    out_path = os.path.join(UPLOAD_DIR, out_filename)
    write_srt_file(out_path, req.entries)

    return {
        "status": "success",
        "download_url": f"/api/download/{out_filename}"
    }
