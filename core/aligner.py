"""
Quran SRT Sync - Forced Alignment Engine
Synchronizes Arabic Quran subtitle text with recitation audio using a hybrid pipeline:
1. Acoustic energy envelope & Voice Activity Detection (VAD)
2. ASR phonetic word timestamp extraction (Whisper)
3. Sequence alignment via dynamic programming and Quranic phonetic similarity
4. Acoustic boundary refinement (speech onset/offset snapping)
5. CapCut timing optimization (padding, global offset, minimum duration, overlap prevention)
"""

import difflib
import numpy as np
import whisper

from .normalizer import (
    normalize_arabic,
    arabic_phonetic_similarity,
    get_phonetic_skeleton,
    tokenize_with_spans
)
from .audio import (
    load_and_resample_audio,
    compute_vad_and_pauses,
    refine_boundary_with_energy
)
from .srt_parser import sec_to_time_str, time_str_to_sec


# Global cached whisper models to avoid reloading on every request
_WHISPER_MODELS = {}


def get_whisper_model(model_name: str = 'small'):
    """Loads or retrieves a cached Whisper model."""
    global _WHISPER_MODELS
    if model_name not in _WHISPER_MODELS:
        _WHISPER_MODELS[model_name] = whisper.load_model(model_name)
    return _WHISPER_MODELS[model_name]


def _extract_asr_words(transcribe_result: dict) -> list[dict]:
    words = []
    for segment in transcribe_result.get('segments', []):
        for word in segment.get('words', []):
            raw = word['word'].strip()
            normalized = normalize_arabic(raw)
            if normalized:
                words.append({
                    'raw': raw,
                    'norm': normalized,
                    'phonetic': get_phonetic_skeleton(normalized),
                    'start': float(word['start']),
                    'end': float(word['end']),
                    'probability': float(word.get('probability', 0.0))
                })
    return words


def _transcribe_words_in_chunks(
    audio: np.ndarray,
    model_name: str,
    sample_rate: int = 16000,
    overlap_seconds: int = 2
) -> list[dict]:
    model = get_whisper_model(model_name)
    chunk_seconds = 20
    chunk_samples = chunk_seconds * sample_rate
    step_samples = (chunk_seconds - overlap_seconds) * sample_rate
    words = []

    for chunk_start in range(0, len(audio), step_samples):
        chunk_end = min(chunk_start + chunk_samples, len(audio))
        result = model.transcribe(
            audio[chunk_start:chunk_end],
            language='ar',
            word_timestamps=True,
            fp16=False
        )
        chunk_start_sec = chunk_start / sample_rate
        ownership_end_sec = min(
            (chunk_start + step_samples) / sample_rate,
            len(audio) / sample_rate
        )
        for word in _extract_asr_words(result):
            word_start = word['start'] + chunk_start_sec
            word_end = word['end'] + chunk_start_sec
            midpoint = (word_start + word_end) / 2
            if chunk_start_sec <= midpoint < ownership_end_sec:
                word['start'] = word_start
                word['end'] = word_end
                words.append(word)

    return words


def _untranscribed_speech_ratio(asr_words: list[dict], vad_info: dict) -> float:
    speech_mask = np.asarray(vad_info['speech_mask'], dtype=bool)
    if not np.any(speech_mask):
        return 0.0

    covered = np.zeros(len(speech_mask), dtype=bool)
    hop_sec = vad_info['hop_sec']
    for word in asr_words:
        start = max(0, int(np.floor(word['start'] / hop_sec)))
        end = min(len(covered), int(np.ceil(word['end'] / hop_sec)))
        covered[start:end] = True

    return float(np.count_nonzero(speech_mask & ~covered) / np.count_nonzero(speech_mask))


def _largest_unmatched_srt_run(srt_entries: list[dict], asr_words: list[dict]) -> int:
    srt_norms = [
        normalized
        for entry in srt_entries
        for token in entry['text'].split()
        if (normalized := normalize_arabic(token))
    ]
    asr_norms = [word['norm'] for word in asr_words]
    matcher = difflib.SequenceMatcher(None, srt_norms, asr_norms)
    return max(
        (i2 - i1 for tag, i1, i2, _, _ in matcher.get_opcodes() if tag == 'delete'),
        default=0
    )


class QuranAligner:
    def __init__(
        self,
        whisper_model_name: str = 'small',
        progress_callback=None
    ):
        self.whisper_model_name = whisper_model_name
        self.progress_callback = progress_callback or (lambda step, total, msg: None)

    def _notify(self, step: int, total: int, msg: str):
        self.progress_callback(step, total, msg)

    def synchronize(
        self,
        audio_path: str,
        srt_entries: list[dict],
        mode: str = 'preserve',              # 'preserve', 'word', 'verse'
        words_per_sub: int = 1,              # For 'word' mode
        global_offset_ms: float = 0.0,       # +/- ms shift for CapCut
        start_padding_ms: float = 60.0,      # ms to start before recitation onset
        end_padding_ms: float = 120.0,       # ms to linger after recitation offset
        min_duration_ms: float = 600.0,      # minimum duration per subtitle
        prevent_overlaps: bool = True,
        gap_buffer_ms: float = 0.0,          # shared boundary between adjacent subtitles
        repetition_mode: str = 'encompass'   # 'encompass' (keep timestamp covering repetition), 'duplicate', 'off'
    ) -> dict:
        """
        Executes the complete synchronization pipeline.
        Returns a dict with:
            - 'synced_entries': list of corrected subtitle dicts
            - 'stats': alignment metrics and summary
            - 'vad_info': detected pauses, silence durations
        """
        TOTAL_STEPS = 6

        # =====================================================================
        # Step 1: Audio Loading & Resampling
        # =====================================================================
        self._notify(1, TOTAL_STEPS, "Loading audio and resampling to 16 kHz float32...")
        audio_16k, total_duration, orig_sr = load_and_resample_audio(audio_path, target_sr=16000)

        # =====================================================================
        # Step 2: Acoustic Energy & VAD Pause Detection
        # =====================================================================
        self._notify(2, TOTAL_STEPS, "Analyzing acoustic energy and detecting breath pauses (Waqf)...")
        vad_info = compute_vad_and_pauses(audio_16k, sr=16000)

        # =====================================================================
        # Step 3: Speech Recognition & Word Timestamps
        # =====================================================================
        self._notify(3, TOTAL_STEPS, f"Running speech recognition with Whisper ({self.whisper_model_name})...")
        requested_model_name = self.whisper_model_name
        used_model_name = requested_model_name

        def transcribe_words(model_name: str, overlap_seconds: int = 2) -> list[dict]:
            return _transcribe_words_in_chunks(audio_16k, model_name, overlap_seconds=overlap_seconds)

        asr_words = transcribe_words(used_model_name)

        if not asr_words:
            raise RuntimeError("No speech words detected in the audio file. Please verify audio content.")

        untranscribed_ratio = _untranscribed_speech_ratio(asr_words, vad_info)
        unmatched_run = _largest_unmatched_srt_run(srt_entries, asr_words)
        if (untranscribed_ratio > 0.12 or unmatched_run > 3) and used_model_name != 'base':
            self._notify(
                3,
                TOTAL_STEPS,
                "Whisper missed speech or subtitle words; retrying with Whisper Base..."
            )
            fallback_words = transcribe_words('base', overlap_seconds=0)
            fallback_ratio = _untranscribed_speech_ratio(fallback_words, vad_info)
            fallback_unmatched_run = _largest_unmatched_srt_run(srt_entries, fallback_words)
            fallback_score = fallback_ratio + (0.5 * fallback_unmatched_run / max(len(srt_entries), 1))
            current_score = untranscribed_ratio + (0.5 * unmatched_run / max(len(srt_entries), 1))
            if fallback_words and fallback_score < current_score:
                asr_words = fallback_words
                used_model_name = 'base'
                untranscribed_ratio = fallback_ratio
                unmatched_run = fallback_unmatched_run

        if untranscribed_ratio > 0.12 or unmatched_run > 3:
            raise RuntimeError(
                "Speech recognition could not align the audio reliably "
                f"({untranscribed_ratio:.0%} of active audio or a run of {unmatched_run} subtitle words was missed). "
                "Try another Whisper model or a clearer audio file."
            )

        # =====================================================================
        # Step 4: Authoritative SRT Text Extraction & Sequence Alignment
        # =====================================================================
        self._notify(4, TOTAL_STEPS, "Aligning authoritative Quranic text to acoustic words...")
        
        # Tokenize authoritative SRT entries into words with original timestamp references
        srt_words = []
        for entry_idx, entry in enumerate(srt_entries):
            raw_tokens = entry['text'].split()
            num_tokens = max(len(raw_tokens), 1)
            e_dur = max(entry['end_sec'] - entry['start_sec'], 0.1)
            for token_pos, raw_tok in enumerate(raw_tokens):
                norm_tok = normalize_arabic(raw_tok)
                if norm_tok:
                    approx_orig_time = entry['start_sec'] + (token_pos / num_tokens) * e_dur
                    srt_words.append({
                        'entry_idx': entry_idx,
                        'token_pos': token_pos,
                        'raw': raw_tok,
                        'norm': norm_tok,
                        'phonetic': get_phonetic_skeleton(norm_tok),
                        'orig_entry': entry,
                        'orig_approx_sec': approx_orig_time
                    })

        if not srt_words:
            raise ValueError("The provided SRT file contains no readable Arabic text.")

        # Align srt_words to asr_words using SequenceMatcher with phonetic similarity
        orig_norms = [w['norm'] for w in srt_words]
        asr_norms = [w['norm'] for w in asr_words]

        matcher = difflib.SequenceMatcher(None, orig_norms, asr_norms)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                # Exact 1-to-1 normalized match
                for o_idx, a_idx in zip(range(i1, i2), range(j1, j2)):
                    srt_words[o_idx]['start'] = asr_words[a_idx]['start']
                    srt_words[o_idx]['end'] = asr_words[a_idx]['end']
                    srt_words[o_idx]['match_type'] = 'exact'

            elif tag == 'replace':
                # ASR misrecognized or split words (e.g. 'المغضوب' -> 'المقدوب', 'انعمت' -> 'ان' 'عنت')
                # Time span covers from start of first ASR word to end of last ASR word
                span_start = asr_words[j1]['start']
                span_end = asr_words[j2 - 1]['end']
                total_span = max(span_end - span_start, 0.1)
                num_orig = i2 - i1

                # Preserve word timing when ASR and subtitle have the same token count.
                if num_orig == (j2 - j1):
                    for o_idx, a_idx in zip(range(i1, i2), range(j1, j2)):
                        similarity = arabic_phonetic_similarity(
                            srt_words[o_idx]['norm'],
                            asr_words[a_idx]['norm']
                        )
                        srt_words[o_idx]['start'] = asr_words[a_idx]['start']
                        srt_words[o_idx]['end'] = asr_words[a_idx]['end']
                        srt_words[o_idx]['match_type'] = (
                            'phonetic' if similarity >= 0.65 else 'substitution'
                        )
                else:
                    # Distribute time proportionally by word length
                    char_counts = [max(len(srt_words[k]['norm']), 1) for k in range(i1, i2)]
                    total_chars = sum(char_counts)
                    curr_t = span_start
                    for rel_idx, k in enumerate(range(i1, i2)):
                        w_dur = total_span * (char_counts[rel_idx] / total_chars)
                        srt_words[k]['start'] = curr_t
                        srt_words[k]['end'] = curr_t + w_dur
                        srt_words[k]['match_type'] = 'interpolated_replace'
                        curr_t += w_dur

            elif tag == 'delete':
                # Present in original SRT, missed by ASR
                # Handled in proportional interpolation pass below
                pass

            elif tag == 'insert':
                # Present in ASR (e.g. breath/noise or repeated syllable), not in authoritative SRT
                pass

        # Interpolate timings for any unassigned words proportionally
        for i in range(len(srt_words)):
            if 'start' not in srt_words[i]:
                prev_end = srt_words[i - 1]['end'] if i > 0 and 'end' in srt_words[i - 1] else 0.0
                next_start = None
                for k in range(i + 1, len(srt_words)):
                    if 'start' in srt_words[k]:
                        next_start = srt_words[k]['start']
                        break
                if next_start is None:
                    next_start = min(prev_end + 0.8, total_duration)

                # Distribute smoothly across available gap
                gap = max(next_start - prev_end, 0.2)
                srt_words[i]['start'] = prev_end
                srt_words[i]['end'] = min(prev_end + (gap * 0.5), next_start)
                srt_words[i]['match_type'] = 'proportional_interpolated'

        # =====================================================================
        # Step 5: Boundary Generation based on Mode
        # =====================================================================
        self._notify(5, TOTAL_STEPS, f"Generating boundaries for mode '{mode}'...")

        raw_synced = []

        if mode == 'word':
            # Word-level synchronization (one subtitle per word or configurable group)
            words_per_sub = max(1, int(words_per_sub))
            for g_start in range(0, len(srt_words), words_per_sub):
                g_words = srt_words[g_start:g_start + words_per_sub]
                sub_text = " ".join(w['raw'] for w in g_words)
                sub_start = g_words[0]['start']
                sub_end = g_words[-1]['end']
                raw_synced.append({
                    'index': len(raw_synced) + 1,
                    'start_sec': sub_start,
                    'end_sec': sub_end,
                    'text': sub_text,
                    'orig_start_sec': g_words[0]['orig_entry']['start_sec'],
                    'orig_end_sec': g_words[-1]['orig_entry']['end_sec']
                })

        else:
            # Default 'preserve' or 'verse' mode:
            # Keeps exact number and order of original SRT entries!
            for entry_idx, entry in enumerate(srt_entries):
                matching_words = [w for w in srt_words if w['entry_idx'] == entry_idx]
                if matching_words:
                    sub_start = matching_words[0]['start']
                    sub_end = matching_words[-1]['end']
                else:
                    sub_start = entry['start_sec']
                    sub_end = entry['end_sec']

                raw_synced.append({
                    'index': entry_idx + 1,
                    'original_index': entry.get('original_index', str(entry_idx + 1)),
                    'start_sec': sub_start,
                    'end_sec': sub_end,
                    'orig_start_sec': entry['start_sec'],
                    'orig_end_sec': entry['end_sec'],
                    'orig_start_str': entry['start_str'],
                    'orig_end_str': entry['end_str'],
                    'text': entry['text']
                })

        # Check and handle repeated verses if enabled
        repetitions_info = []
        if mode != 'word' and repetition_mode != 'off':
            raw_synced, repetitions_info = self._handle_verse_repetitions(
                raw_synced, asr_words, repetition_mode=repetition_mode
            )

        # =====================================================================
        # Step 6: Acoustic Refinement, Padding & CapCut Post-Processing
        # =====================================================================
        self._notify(6, TOTAL_STEPS, "Applying acoustic boundary refinement & CapCut timing post-processing...")

        global_offset = global_offset_ms / 1000.0
        start_pad = start_padding_ms / 1000.0
        end_pad = end_padding_ms / 1000.0
        min_dur = min_duration_ms / 1000.0
        gap_buf = gap_buffer_ms / 1000.0

        processed = []
        for item in raw_synced:
            s = item['start_sec']
            e = item['end_sec']

            # Acoustic energy snapping to true vocal onset and offset
            s_snapped = refine_boundary_with_energy(s, is_start=True, vad_info=vad_info)
            e_snapped = refine_boundary_with_energy(e, is_start=False, vad_info=vad_info)

            # Apply padding & global offset
            s_final = s_snapped - start_pad + global_offset
            e_final = e_snapped + end_pad + global_offset

            # Clamp within audio duration
            s_final = max(0.0, s_final)
            e_final = min(total_duration, e_final)

            # Enforce minimum duration
            if (e_final - s_final) < min_dur:
                e_final = min(total_duration, s_final + min_dur)

            processed.append({
                'index': item['index'],
                'start_sec': round(s_final, 3),
                'end_sec': round(e_final, 3),
                'orig_start_sec': item.get('orig_start_sec', 0.0),
                'orig_end_sec': item.get('orig_end_sec', 0.0),
                'orig_start_str': item.get('orig_start_str', sec_to_time_str(item.get('orig_start_sec', 0.0))),
                'orig_end_str': item.get('orig_end_str', sec_to_time_str(item.get('orig_end_sec', 0.0))),
                'start_str': sec_to_time_str(s_final),
                'end_str': sec_to_time_str(e_final),
                'text': item['text'],
                'has_repetition': item.get('has_repetition', False)
            })

        # Make adjacent cues contiguous while preventing them from overlapping.
        if prevent_overlaps:
            for i in range(len(processed) - 1):
                curr_item = processed[i]
                next_item = processed[i + 1]

                if curr_item['end_sec'] < next_item['start_sec']:
                    curr_item['end_sec'] = next_item['start_sec']
                    curr_item['end_str'] = next_item['start_str']
                elif curr_item['end_sec'] > next_item['start_sec']:
                    boundary = round(
                        (curr_item['end_sec'] + next_item['start_sec'] - gap_buf) / 2,
                        3
                    )
                    if boundary > curr_item['start_sec']:
                        curr_item['end_sec'] = boundary
                        curr_item['end_str'] = sec_to_time_str(curr_item['end_sec'])
                        next_item['start_sec'] = round(boundary + gap_buf, 3)
                        next_item['start_str'] = sec_to_time_str(next_item['start_sec'])
                    else:
                        # If tightly packed, adjust next start
                        next_item['start_sec'] = round(curr_item['end_sec'] + gap_buf, 3)
                        next_item['start_str'] = sec_to_time_str(next_item['start_sec'])

        # Compute shift stats
        shifts = []
        for p in processed:
            shift = p['start_sec'] - p['orig_start_sec']
            p['shift_sec'] = round(shift, 3)
            shifts.append(shift)

        avg_shift = np.mean(shifts) if shifts else 0.0
        max_shift = np.max(np.abs(shifts)) if shifts else 0.0

        stats = {
            'total_subtitles': len(processed),
            'audio_duration_sec': round(total_duration, 2),
            'average_shift_sec': round(float(avg_shift), 3),
            'max_shift_sec': round(float(max_shift), 3),
            'num_pauses_detected': len(vad_info['pauses']),
            'num_repetitions_detected': len(repetitions_info),
            'repeated_verses': repetitions_info,
            'repetition_mode': repetition_mode,
            'intro_silence_sec': vad_info['intro_silence_sec'],
            'outro_silence_sec': vad_info['outro_silence_sec'],
            'whisper_model': used_model_name,
            'requested_whisper_model': requested_model_name,
            'used_model_fallback': used_model_name != requested_model_name,
            'mode': mode
        }

        return {
            'synced_entries': processed,
            'stats': stats,
            'vad_info': {
                'pauses': vad_info['pauses'],
                'intro_silence_sec': vad_info['intro_silence_sec'],
                'outro_silence_sec': vad_info['outro_silence_sec'],
                'total_duration': vad_info['total_duration']
            }
        }

    def _handle_verse_repetitions(
        self,
        raw_synced: list[dict],
        asr_words: list[dict],
        repetition_mode: str = 'encompass'
    ) -> tuple[list[dict], list[dict]]:
        """
        Detects if the reciter repeated a verse (e.g. recited twice) in the audio.
        If repetition_mode == 'encompass' (default):
            Encompasses the repetition in the same subtitle entry, keeping start at the
            beginning of rendition 1 and extending end to the conclusion of rendition 2.
        If repetition_mode == 'duplicate':
            Inserts a duplicate subtitle entry for the repeated recitation.
        """
        updated = []
        repetitions_detected = []

        for i, item in enumerate(raw_synced):
            curr_start = item['start_sec']
            curr_end = item['end_sec']
            next_start = raw_synced[i + 1]['start_sec'] if i + 1 < len(raw_synced) else float('inf')
            prev_end = raw_synced[i - 1]['end_sec'] if i > 0 else 0.0

            verse_raw_words = item['text'].split()
            verse_norm_words = [normalize_arabic(w) for w in verse_raw_words if normalize_arabic(w)]

            # 1. Check for repetition AFTER current end (reciter pauses and repeats the verse)
            post_words = [
                w for w in asr_words
                if w['start'] >= curr_end - 0.25 and w['end'] <= next_start + 0.25
            ]
            rep_end = None
            rep_post_words = []
            if post_words and verse_norm_words:
                post_norms = [w['norm'] for w in post_words]
                full_ratio = difflib.SequenceMatcher(None, verse_norm_words, post_norms).ratio()
                tail_len = min(len(post_norms), len(verse_norm_words))
                tail_ratio = (
                    difflib.SequenceMatcher(None, verse_norm_words[-tail_len:], post_norms[:tail_len]).ratio()
                    if tail_len > 0 else 0.0
                )

                if full_ratio >= 0.55 or tail_ratio >= 0.65:
                    rep_start = post_words[0]['start']
                    rep_end = post_words[-1]['end']
                    rep_post_words = post_words
                    repetitions_detected.append({
                        'entry_index': item['index'],
                        'verse_text': item['text'],
                        'type': 'post_repeat',
                        'rep_start_sec': round(rep_start, 3),
                        'rep_end_sec': round(rep_end, 3)
                    })

            # 2. Check for repetition BEFORE current start (if primary alignment matched rendition 2)
            pre_words = [
                w for w in asr_words
                if w['start'] >= prev_end - 0.25 and w['end'] <= curr_start + 0.25
            ]
            rep_pre_start = None
            if pre_words and verse_norm_words:
                pre_norms = [w['norm'] for w in pre_words]
                pre_ratio = difflib.SequenceMatcher(None, verse_norm_words, pre_norms).ratio()
                if pre_ratio >= 0.55:
                    rep_pre_start = pre_words[0]['start']
                    repetitions_detected.append({
                        'entry_index': item['index'],
                        'verse_text': item['text'],
                        'type': 'pre_repeat',
                        'rep_start_sec': round(rep_pre_start, 3),
                        'rep_end_sec': round(pre_words[-1]['end'], 3)
                    })

            if repetition_mode == 'encompass':
                final_s = rep_pre_start if rep_pre_start is not None else curr_start
                final_e = rep_end if rep_end is not None else curr_end
                item_copy = dict(item)
                item_copy['start_sec'] = final_s
                item_copy['end_sec'] = final_e
                item_copy['has_repetition'] = (rep_end is not None or rep_pre_start is not None)
                updated.append(item_copy)

            elif repetition_mode == 'duplicate':
                item_copy = dict(item)
                item_copy['has_repetition'] = (rep_end is not None or rep_pre_start is not None)
                updated.append(item_copy)
                if rep_end is not None and rep_post_words:
                    dup_item = dict(item)
                    dup_item['start_sec'] = rep_post_words[0]['start']
                    dup_item['end_sec'] = rep_end
                    dup_item['is_repetition_duplicate'] = True
                    updated.append(dup_item)
            else:
                updated.append(dict(item))

        return updated, repetitions_detected
