"""
Quran SRT Sync - Audio Processing & Acoustic Analysis
Handles audio loading, polyphase resampling to 16kHz float32, RMS energy envelope,
Voice Activity Detection (VAD), silence/pause detection, and acoustic boundary refinement.
"""

import os
import numpy as np
import scipy.signal as sps
import soundfile as sf


def load_and_resample_audio(audio_path: str, target_sr: int = 16000) -> tuple[np.ndarray, float, int]:
    """
    Loads an audio file (MP3, WAV, FLAC, OGG, etc.) and resamples to target_sr (default 16000 Hz) mono float32.
    Returns:
        (audio_16k, duration_sec, original_sr)
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Read audio with soundfile
    try:
        data, orig_sr = sf.read(audio_path, dtype='float32')
    except Exception as e:
        raise RuntimeError(f"Failed to read audio file '{audio_path}': {str(e)}")

    # Downmix stereo/multichannel to mono
    if data.ndim > 1:
        mono = data.mean(axis=1)
    else:
        mono = data

    total_samples = len(mono)
    duration_sec = total_samples / orig_sr

    # Resample if needed
    if orig_sr != target_sr:
        # Use polyphase rational resampling for high acoustic fidelity
        gcd = np.gcd(int(target_sr), int(orig_sr))
        up = int(target_sr // gcd)
        down = int(orig_sr // gcd)
        audio_resampled = sps.resample_poly(mono, up, down).astype(np.float32)
    else:
        audio_resampled = mono.astype(np.float32)

    # Normalize amplitude to [-1.0, 1.0] if needed
    peak = np.max(np.abs(audio_resampled))
    if peak > 1.0:
        audio_resampled = audio_resampled / peak

    return audio_resampled, duration_sec, orig_sr


def compute_energy_envelope(
    audio_16k: np.ndarray,
    frame_ms: float = 25.0,
    hop_ms: float = 10.0,
    sr: int = 16000
) -> tuple[np.ndarray, float]:
    """
    Computes the Short-Time Root Mean Square (RMS) energy envelope.
    Returns:
        (energy_envelope, hop_sec)
    """
    frame_len = int(round(sr * (frame_ms / 1000.0)))
    hop_len = int(round(sr * (hop_ms / 1000.0)))
    hop_sec = hop_len / sr

    if len(audio_16k) < frame_len:
        return np.zeros(1, dtype=np.float32), hop_sec

    # Pad audio to cover full frames
    pad_len = frame_len - (len(audio_16k) % hop_len)
    padded = np.pad(audio_16k, (0, pad_len), mode='constant')

    # Windowed frames squared
    shape = ((len(padded) - frame_len) // hop_len + 1, frame_len)
    strides = (padded.strides[0] * hop_len, padded.strides[0])
    frames = np.lib.stride_tricks.as_strided(padded, shape=shape, strides=strides)

    # Compute RMS energy per frame
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    return rms, hop_sec


def compute_vad_and_pauses(
    audio_16k: np.ndarray,
    sr: int = 16000,
    frame_ms: float = 25.0,
    hop_ms: float = 10.0,
    min_pause_ms: float = 250.0
) -> dict:
    """
    Voice Activity Detection tailored for Quranic recitation.
    Detects:
    - Adaptive silence floor
    - Active recitation intervals
    - Inter-verse and intra-verse breath pauses (Waqf)
    - Intro silence and outro silence
    """
    rms, hop_sec = compute_energy_envelope(audio_16k, frame_ms, hop_ms, sr)
    total_duration = len(audio_16k) / sr

    # Compute adaptive speech threshold
    # Recitations have quiet background / breath noise and high vocal energy
    sorted_rms = np.sort(rms)
    noise_floor = float(np.percentile(sorted_rms, 15))
    peak_energy = float(np.percentile(sorted_rms, 95))
    
    # Adaptive threshold between noise floor and peak
    energy_range = max(peak_energy - noise_floor, 1e-6)
    speech_threshold = noise_floor + 0.08 * energy_range

    is_speech = rms > speech_threshold

    # Morphological closing/opening to remove micro-glitches < 80ms
    min_speech_frames = int(round(0.08 / hop_sec))
    min_pause_frames = int(round(min_pause_ms / 1000.0 / hop_sec))

    # Clean up speech mask
    cleaned_speech = np.copy(is_speech)

    # Bridge brief micro-drops within words (e.g. unvoiced consonants, stops)
    bridge_frames = int(round(0.12 / hop_sec))
    gap = 0
    for i in range(len(cleaned_speech)):
        if not cleaned_speech[i]:
            gap += 1
        else:
            if 0 < gap <= bridge_frames:
                cleaned_speech[i - gap:i] = True
            gap = 0

    # Find pause segments (Waqf)
    pauses = []
    in_pause = False
    pause_start = 0.0

    for i, active in enumerate(cleaned_speech):
        t = i * hop_sec
        if not active:
            if not in_pause:
                in_pause = True
                pause_start = t
        else:
            if in_pause:
                in_pause = False
                pause_dur = t - pause_start
                if pause_dur >= (min_pause_ms / 1000.0):
                    pauses.append({
                        'start': round(pause_start, 3),
                        'end': round(t, 3),
                        'duration': round(pause_dur, 3)
                    })

    if in_pause:
        pause_dur = total_duration - pause_start
        if pause_dur >= (min_pause_ms / 1000.0):
            pauses.append({
                'start': round(pause_start, 3),
                'end': round(total_duration, 3),
                'duration': round(pause_dur, 3)
            })

    # Detect intro silence
    intro_silence = 0.0
    for i, active in enumerate(cleaned_speech):
        if active:
            intro_silence = i * hop_sec
            break

    # Detect outro silence
    outro_silence = 0.0
    for i in range(len(cleaned_speech) - 1, -1, -1):
        if cleaned_speech[i]:
            outro_silence = total_duration - (i * hop_sec)
            break

    return {
        'rms': rms,
        'hop_sec': hop_sec,
        'speech_threshold': speech_threshold,
        'noise_floor': noise_floor,
        'peak_energy': peak_energy,
        'speech_mask': cleaned_speech,
        'pauses': pauses,
        'intro_silence_sec': round(intro_silence, 3),
        'outro_silence_sec': round(outro_silence, 3),
        'total_duration': round(total_duration, 3)
    }


def refine_boundary_with_energy(
    time_sec: float,
    is_start: bool,
    vad_info: dict,
    search_window: float = 0.40
) -> float:
    """
    Snaps an estimated start or end timestamp to the exact acoustic energy boundary.
    - If is_start=True: searches in [time_sec - search_window, time_sec + search_window]
      for the transition from silence to speech onset.
    - If is_start=False: searches in [time_sec - search_window, time_sec + search_window]
      for the transition from speech into pause/decay.
    """
    rms = vad_info['rms']
    hop_sec = vad_info['hop_sec']
    threshold = vad_info['speech_threshold']
    total_dur = vad_info['total_duration']

    center_frame = int(round(time_sec / hop_sec))
    window_frames = int(round(search_window / hop_sec))

    min_f = max(0, center_frame - window_frames)
    max_f = min(len(rms) - 1, center_frame + window_frames)

    if min_f >= max_f:
        return max(0.0, min(time_sec, total_dur))

    if is_start:
        # Snap only to an actual silence-to-speech transition, not any speech
        # already underway in the search window.
        candidates = [
            f for f in range(min_f, max_f + 1)
            if rms[f] >= threshold and (f == 0 or rms[f - 1] < threshold)
        ]
    else:
        # Snap only to an actual speech-to-silence transition.
        candidates = [
            f for f in range(max(min_f, 1), max_f + 1)
            if rms[f - 1] >= threshold and rms[f] < threshold
        ]

    if not candidates:
        return max(0.0, min(time_sec, total_dur))

    nearest = min(candidates, key=lambda frame: abs(frame * hop_sec - time_sec))
    return round(min(total_dur, nearest * hop_sec), 3)
