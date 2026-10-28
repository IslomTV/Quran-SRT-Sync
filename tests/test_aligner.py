"""
Unit tests for Quran SRT Sync core components.
"""

import os
import unittest
from unittest.mock import Mock, patch
from core.normalizer import (
    normalize_arabic,
    strip_tashkeel,
    arabic_phonetic_similarity,
    get_phonetic_skeleton
)
from core.srt_parser import time_str_to_sec, sec_to_time_str, parse_srt_content, generate_srt_string
from core.quran_db import detect_surah_from_text
from core.aligner import (
    QuranAligner,
    _transcribe_words_in_chunks,
    _untranscribed_speech_ratio
)
from core.audio import refine_boundary_with_energy


class TestQuranSRTSync(unittest.TestCase):

    def test_normalizer(self):
        text_with_diacritics = "﻿بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ"
        norm = normalize_arabic(text_with_diacritics)
        self.assertEqual(norm, "بسم الله الرحمن الرحيم")

        # Test Alif normalization
        self.assertEqual(normalize_arabic("إِيَّاكَ"), "اياك")
        self.assertEqual(normalize_arabic("أَنْعَمْتَ"), "انعمت")

        # Test Taa Marbuta
        self.assertEqual(normalize_arabic("سورة"), "سوره")

        # Test Alif Maqsura
        self.assertEqual(normalize_arabic("هدى"), "هدي")

    def test_phonetic_similarity(self):
        # Exact
        self.assertAlmostEqual(arabic_phonetic_similarity("الرحمن", "الرحمن"), 1.0)
        # Normalized
        self.assertGreater(arabic_phonetic_similarity("ٱلرَّحْمَٰنِ", "الرحمن"), 0.90)
        # ASR phonetic confusions
        self.assertGreater(arabic_phonetic_similarity("الصراط", "الصراق"), 0.80)
        self.assertGreater(arabic_phonetic_similarity("المستقيم", "المستطين"), 0.70)

    def test_srt_parser(self):
        srt_sample = """1
00:00:01,500 --> 00:00:05,250
بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ

2
00:00:05,250 --> 00:00:09,800
الْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ
"""
        entries = parse_srt_content(srt_sample)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['start_sec'], 1.5)
        self.assertEqual(entries[0]['end_sec'], 5.25)
        self.assertEqual(entries[1]['start_sec'], 5.25)
        self.assertEqual(entries[1]['end_sec'], 9.8)

        # Roundtrip
        reserialized = generate_srt_string(entries)
        entries2 = parse_srt_content(reserialized)
        self.assertEqual(len(entries2), 2)
        self.assertEqual(entries2[0]['start_str'], "00:00:01,500")

    def test_surah_detection(self):
        surah = detect_surah_from_text("الحمد لله رب العالمين الرحمن الرحيم")
        self.assertIsNotNone(surah)
        self.assertEqual(surah['number'], 1)
        self.assertEqual(surah['english_name'], "Al-Fatihah")

    def test_full_alignment(self):
        audio_path = r"C:\Users\Family\.gemini\antigravity\scratch\quran-srt-sync\samples\al_fatiha.mp3"
        srt_path = r"C:\Users\Family\.gemini\antigravity\scratch\quran-srt-sync\samples\al_fatiha_original.srt"
        
        from core.srt_parser import read_srt_file
        entries = read_srt_file(srt_path)
        self.assertEqual(len(entries), 7)

        aligner = QuranAligner(whisper_model_name='tiny')
        result = aligner.synchronize(audio_path, entries, mode='preserve')

        synced = result['synced_entries']
        self.assertEqual(len(synced), 7)
        for i in range(len(synced) - 1):
            self.assertLess(synced[i]['start_sec'], synced[i]['end_sec'])
            self.assertLessEqual(synced[i]['end_sec'], synced[i+1]['start_sec'])

    def test_overlap_prevention_uses_shared_boundary(self):
        entries = [
            {
                'index': 1, 'original_index': '1', 'start_sec': 0.2, 'end_sec': 1.0,
                'start_str': '00:00:00,200', 'end_str': '00:00:01,000', 'text': 'الحمد'
            },
            {
                'index': 2, 'original_index': '2', 'start_sec': 0.95, 'end_sec': 1.8,
                'start_str': '00:00:00,950', 'end_str': '00:00:01,800', 'text': 'لله'
            }
        ]
        model = Mock()
        model.transcribe.return_value = {
            'segments': [{
                'words': [
                    {'word': ' الحمد', 'start': 0.2, 'end': 1.0},
                    {'word': ' لله', 'start': 0.95, 'end': 1.8}
                ]
            }]
        }

        with patch('core.aligner.load_and_resample_audio', return_value=([0.0] * 32000, 2.0, 16000)), \
                patch('core.aligner.compute_vad_and_pauses', return_value={
                    'pauses': [], 'intro_silence_sec': 0.0, 'outro_silence_sec': 0.0,
                    'total_duration': 2.0, 'speech_mask': [False] * 200, 'hop_sec': 0.01
                }), \
                patch('core.aligner.get_whisper_model', return_value=model), \
                patch('core.aligner.refine_boundary_with_energy', side_effect=lambda time_sec, **kwargs: time_sec):
            result = QuranAligner().synchronize(
                'unused.mp3',
                entries,
                start_padding_ms=0,
                end_padding_ms=0,
                min_duration_ms=0,
                repetition_mode='off'
            )

        synced = result['synced_entries']
        self.assertEqual(synced[0]['end_sec'], synced[1]['start_sec'])
        self.assertEqual(synced[0]['end_str'], synced[1]['start_str'])
        self.assertEqual(synced[0]['end_sec'], 0.975)

    def test_overlap_prevention_closes_gaps_between_subtitles(self):
        entries = [
            {
                'index': 1, 'original_index': '1', 'start_sec': 0.2, 'end_sec': 1.0,
                'start_str': '00:00:00,200', 'end_str': '00:00:01,000', 'text': 'الحمد'
            },
            {
                'index': 2, 'original_index': '2', 'start_sec': 2.0, 'end_sec': 2.8,
                'start_str': '00:00:02,000', 'end_str': '00:00:02,800', 'text': 'لله'
            }
        ]
        model = Mock()
        model.transcribe.return_value = {
            'segments': [{
                'words': [
                    {'word': ' الحمد', 'start': 0.2, 'end': 1.0},
                    {'word': ' لله', 'start': 2.0, 'end': 2.8}
                ]
            }]
        }

        with patch('core.aligner.load_and_resample_audio', return_value=([0.0] * 48000, 3.0, 16000)), \
                patch('core.aligner.compute_vad_and_pauses', return_value={
                    'pauses': [], 'intro_silence_sec': 0.0, 'outro_silence_sec': 0.0,
                    'total_duration': 3.0, 'speech_mask': [False] * 300, 'hop_sec': 0.01
                }), \
                patch('core.aligner.get_whisper_model', return_value=model), \
                patch('core.aligner.refine_boundary_with_energy', side_effect=lambda time_sec, **kwargs: time_sec):
            result = QuranAligner().synchronize(
                'unused.mp3',
                entries,
                start_padding_ms=0,
                end_padding_ms=0,
                min_duration_ms=0,
                repetition_mode='off'
            )

        synced = result['synced_entries']
        self.assertEqual(synced[0]['end_sec'], synced[1]['start_sec'])
        self.assertEqual(synced[0]['end_str'], synced[1]['start_str'])
        self.assertEqual(synced[0]['end_sec'], 2.0)

    def test_alignment_preserves_word_times_in_mismatched_equal_length_block(self):
        entries = [
            {
                'index': 1, 'original_index': '1', 'start_sec': 0.0, 'end_sec': 5.0,
                'start_str': '00:00:00,000', 'end_str': '00:00:05,000',
                'text': 'وَٱلْعَٰدِيَٰتِ ضَبْحًا'
            },
            {
                'index': 2, 'original_index': '2', 'start_sec': 5.0, 'end_sec': 10.0,
                'start_str': '00:00:05,000', 'end_str': '00:00:10,000',
                'text': 'فَٱلْمُورِيَٰتِ قَدْحًا'
            }
        ]
        model = Mock()
        model.transcribe.return_value = {
            'segments': [{
                'words': [
                    {'word': ' والعاديات', 'start': 3.28, 'end': 5.14},
                    {'word': ' ضبحه', 'start': 5.14, 'end': 6.5},
                    {'word': ' فالموريات', 'start': 6.5, 'end': 8.04},
                    {'word': ' قدحه', 'start': 8.04, 'end': 9.42}
                ]
            }]
        }

        with patch('core.aligner.load_and_resample_audio', return_value=([0.0] * 160000, 10.0, 16000)), \
                patch('core.aligner.compute_vad_and_pauses', return_value={
                    'pauses': [], 'intro_silence_sec': 0.0, 'outro_silence_sec': 0.0,
                    'total_duration': 10.0, 'speech_mask': [False] * 1000, 'hop_sec': 0.01
                }), \
                patch('core.aligner.get_whisper_model', return_value=model), \
                patch('core.aligner.refine_boundary_with_energy', side_effect=lambda time_sec, **kwargs: time_sec):
            result = QuranAligner().synchronize(
                'unused.mp3',
                entries,
                start_padding_ms=0,
                end_padding_ms=0,
                min_duration_ms=0,
                repetition_mode='off'
            )

        synced = result['synced_entries']
        self.assertEqual(synced[0]['start_sec'], 3.28)
        self.assertEqual(synced[0]['end_sec'], 6.5)
        self.assertEqual(synced[1]['start_sec'], 6.5)
        self.assertEqual(synced[1]['end_sec'], 9.42)

    def test_alignment_retries_base_when_selected_model_misses_speech(self):
        entries = [
            {
                'index': 1, 'original_index': '1', 'start_sec': 0.0, 'end_sec': 5.0,
                'start_str': '00:00:00,000', 'end_str': '00:00:05,000', 'text': 'الحمد'
            },
            {
                'index': 2, 'original_index': '2', 'start_sec': 5.0, 'end_sec': 10.0,
                'start_str': '00:00:05,000', 'end_str': '00:00:10,000', 'text': 'لله'
            }
        ]
        small_model = Mock()
        small_model.transcribe.return_value = {
            'segments': [{
                'words': [
                    {'word': ' الحمد', 'start': 0.1, 'end': 1.0},
                    {'word': ' لله', 'start': 8.0, 'end': 9.0}
                ]
            }]
        }
        base_model = Mock()
        base_model.transcribe.return_value = {
            'segments': [{
                'words': [
                    {'word': ' الحمد', 'start': 0.0, 'end': 5.0},
                    {'word': ' لله', 'start': 5.0, 'end': 10.0}
                ]
            }]
        }

        with patch('core.aligner.load_and_resample_audio', return_value=([0.0] * 160000, 10.0, 16000)), \
                patch('core.aligner.compute_vad_and_pauses', return_value={
                    'pauses': [], 'intro_silence_sec': 0.0, 'outro_silence_sec': 0.0,
                    'total_duration': 10.0, 'speech_mask': [True] * 1000, 'hop_sec': 0.01
                }), \
                patch('core.aligner.get_whisper_model', side_effect={
                    'small': small_model, 'base': base_model
                }.get), \
                patch('core.aligner.refine_boundary_with_energy', side_effect=lambda time_sec, **kwargs: time_sec):
            result = QuranAligner(whisper_model_name='small').synchronize(
                'unused.mp3',
                entries,
                start_padding_ms=0,
                end_padding_ms=0,
                min_duration_ms=0,
                repetition_mode='off'
            )

        self.assertEqual(result['stats']['whisper_model'], 'base')
        self.assertTrue(result['stats']['used_model_fallback'])
        self.assertEqual(base_model.transcribe.call_count, 1)

    def test_chunked_transcription_uses_non_overlapping_windows(self):
        model = Mock()
        model.transcribe.side_effect = [
            {'segments': [{'words': [{'word': ' الحمد', 'start': 19.0, 'end': 19.5}]}]},
            {'segments': [{'words': [{'word': ' لله', 'start': 1.0, 'end': 1.5}]}]}
        ]

        with patch('core.aligner.get_whisper_model', return_value=model):
            words = _transcribe_words_in_chunks(
                [0.0] * 400000,
                'base',
                overlap_seconds=0
            )

        self.assertEqual(model.transcribe.call_count, 2)
        self.assertEqual(len(model.transcribe.call_args_list[0].args[0]), 320000)
        self.assertEqual(len(model.transcribe.call_args_list[1].args[0]), 80000)
        self.assertEqual([word['start'] for word in words], [19.0, 21.0])

    def test_untranscribed_speech_ratio_ignores_silence(self):
        ratio = _untranscribed_speech_ratio(
            [{'start': 0.1, 'end': 0.3}],
            {'speech_mask': [False, True, True, False], 'hop_sec': 0.1}
        )
        self.assertEqual(ratio, 0.0)

    def test_energy_refinement_uses_nearest_transition(self):
        vad_info = {
            'rms': [0.0, 0.0, 1.0, 1.0, 0.0, 0.0],
            'hop_sec': 0.1,
            'speech_threshold': 0.5,
            'total_duration': 0.6
        }

        self.assertEqual(
            refine_boundary_with_energy(0.31, is_start=True, vad_info=vad_info, search_window=0.4),
            0.2
        )
        self.assertEqual(
            refine_boundary_with_energy(0.39, is_start=False, vad_info=vad_info, search_window=0.4),
            0.4
        )

    def test_energy_refinement_does_not_snap_to_ongoing_speech(self):
        vad_info = {
            'rms': [0.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            'hop_sec': 0.1,
            'speech_threshold': 0.5,
            'total_duration': 0.6
        }

        self.assertEqual(
            refine_boundary_with_energy(0.4, is_start=True, vad_info=vad_info, search_window=0.2),
            0.4
        )

    def test_repetition_encompassing(self):
        """Tests that when a verse is recited twice, the timestamp encompasses the repetition."""
        aligner = QuranAligner(whisper_model_name='tiny')
        raw_synced = [
            {"index": 1, "text": "ٱلْحَمْدُ لِلَّهِ رَبِّ ٱلْعَٰلَمِينَ", "start_sec": 0.5, "end_sec": 5.0},
            {"index": 2, "text": "ٱلرَّحْمَٰنِ ٱلرَّحِيمِ", "start_sec": 5.8, "end_sec": 9.5},
            {"index": 3, "text": "مَٰلِكِ يَوْمِ ٱلدِّينِ", "start_sec": 15.6, "end_sec": 20.0}
        ]
        # ASR with Verse 2 repeated at 10.8 -> 14.8
        asr_words = [
            {"norm": "الحمد", "start": 0.5, "end": 1.5},
            {"norm": "لله", "start": 1.5, "end": 2.5},
            {"norm": "رب", "start": 2.5, "end": 3.2},
            {"norm": "العالمين", "start": 3.2, "end": 5.0},
            {"norm": "الرحمن", "start": 5.8, "end": 7.2},
            {"norm": "الرحيم", "start": 7.2, "end": 9.5},
            # Repeated rendition
            {"norm": "الرحمن", "start": 10.8, "end": 12.4},
            {"norm": "الرحيم", "start": 12.4, "end": 14.8},
            {"norm": "ملك", "start": 15.6, "end": 16.8},
            {"norm": "يوم", "start": 16.8, "end": 17.5},
            {"norm": "الدين", "start": 17.5, "end": 20.0}
        ]
        updated, reps = aligner._handle_verse_repetitions(raw_synced, asr_words, repetition_mode='encompass')
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0]['entry_index'], 2)
        # Verse 2 end should be extended to cover the repeated recitation at 14.8s
        self.assertEqual(updated[1]['start_sec'], 5.8)
        self.assertEqual(updated[1]['end_sec'], 14.8)
        self.assertTrue(updated[1]['has_repetition'])


if __name__ == '__main__':
    unittest.main()
