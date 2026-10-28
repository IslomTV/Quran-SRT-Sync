import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cli
from core.bulk import pair_bulk_files
from core.srt_parser import read_srt_file


class TestBulkProcessing(unittest.TestCase):
    def test_pairs_zero_padded_mp3_with_arabic_srt_by_numeric_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio_dir = root / 'audio'
            srt_dir = root / 'srt'
            audio_dir.mkdir()
            srt_dir.mkdir()
            audio = audio_dir / '080.mp3'
            subtitle = srt_dir / '80_arabic.srt'
            audio.touch()
            subtitle.touch()
            (srt_dir / '80_english.srt').touch()
            (srt_dir / '81_arabic_corrected.srt').touch()

            pairing = pair_bulk_files(audio_dir, srt_dir)

            self.assertEqual(pairing.matches, [(audio, subtitle)])
            self.assertEqual(pairing.unmatched_audio, [])
            self.assertEqual(pairing.unmatched_srt, [])
            self.assertEqual(pairing.errors, [])

    def test_reports_duplicate_numeric_ids_as_ambiguous(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio_dir = root / 'audio'
            srt_dir = root / 'srt'
            audio_dir.mkdir()
            srt_dir.mkdir()
            (audio_dir / '080.mp3').touch()
            (audio_dir / '80.mp3').touch()
            (srt_dir / '80_arabic.srt').touch()

            pairing = pair_bulk_files(audio_dir, srt_dir)

            self.assertEqual(pairing.matches, [])
            self.assertTrue(any('same numeric ID 80' in error for error in pairing.errors))

    def test_pair_order_is_driven_by_sorted_mp3_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio_dir = root / 'audio'
            srt_dir = root / 'srt'
            audio_dir.mkdir()
            srt_dir.mkdir()
            (audio_dir / '080.mp3').touch()
            (audio_dir / '002.mp3').touch()
            (srt_dir / '80_arabic.srt').touch()
            (srt_dir / '2_arabic.srt').touch()

            pairing = pair_bulk_files(audio_dir, srt_dir)

            self.assertEqual(
                [audio.name for audio, _ in pairing.matches],
                ['002.mp3', '080.mp3']
            )

    def test_bulk_writes_corrected_files_in_srt_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio_dir = root / 'audio'
            srt_dir = root / 'srt'
            audio_dir.mkdir()
            srt_dir.mkdir()
            (audio_dir / '080.mp3').touch()
            subtitle = srt_dir / '80_arabic.srt'
            subtitle.write_text(
                '1\n00:00:00,000 --> 00:00:01,000\nالحمد لله\n',
                encoding='utf-8'
            )
            entries = read_srt_file(str(subtitle))

            aligner = Mock()
            aligner.synchronize.return_value = {
                'synced_entries': entries,
                'stats': {}
            }
            args = argparse.Namespace(
                audio_dir=str(audio_dir),
                srt_dir=str(srt_dir),
                model='small',
                mode='preserve',
                words_per_sub=1,
                offset=0.0,
                start_pad=60.0,
                end_pad=120.0,
                min_dur=600.0,
                allow_overlaps=False,
                repeat_mode='encompass'
            )

            with patch('cli.QuranAligner', return_value=aligner), contextlib.redirect_stdout(io.StringIO()):
                status = cli.run_bulk(args)

            output_path = srt_dir / 'corrected' / '80_arabic_corrected.srt'
            self.assertEqual(status, 0)
            self.assertTrue(output_path.is_file())
            self.assertEqual(aligner.synchronize.call_args.kwargs['audio_path'], str(audio_dir / '080.mp3'))
            self.assertEqual(read_srt_file(str(output_path))[0]['text'], 'الحمد لله')


if __name__ == '__main__':
    unittest.main()
