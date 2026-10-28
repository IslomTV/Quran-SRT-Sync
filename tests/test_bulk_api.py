import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException

import app
from core.srt_parser import read_srt_file


class TestBulkApi(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.audio_dir = self.root / "audio"
        self.srt_dir = self.root / "srt"
        self.audio_dir.mkdir()
        self.srt_dir.mkdir()
        (self.audio_dir / "080.mp3").touch()
        self.srt_path = self.srt_dir / "80_arabic.srt"
        self.srt_path.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nالحمد لله\n",
            encoding="utf-8"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_preview_returns_mp3_first_match_and_pairing_issues(self):
        (self.audio_dir / "081.mp3").touch()
        result = app.preview_bulk_pairs(app.BulkDirectoriesRequest(
            audio_dir=str(self.audio_dir),
            srt_dir=str(self.srt_dir)
        ))

        self.assertEqual(
            result["matches"],
            [{"audio_filename": "080.mp3", "srt_filename": "80_arabic.srt"}]
        )
        self.assertTrue(any("081.mp3" in issue for issue in result["issues"]))
        self.assertEqual(result["output_dir"], str(self.audio_dir))

    def test_pair_sync_rejects_pair_not_found_by_current_directory_scan(self):
        request = app.BulkPairSyncRequest(
            audio_dir=str(self.audio_dir),
            srt_dir=str(self.srt_dir),
            audio_filename="080.mp3",
            srt_filename="81_arabic.srt"
        )

        with self.assertRaises(HTTPException) as error:
            app.synchronize_bulk_pair(request)

        self.assertEqual(error.exception.status_code, 400)

    def test_pair_sync_saves_arabic_srt_in_audio_directory(self):
        entries = read_srt_file(str(self.srt_path))
        aligner = Mock()
        aligner.synchronize.return_value = {
            "synced_entries": entries,
            "stats": {"alignment_warning": "Review low-confidence subtitles."}
        }
        request = app.BulkPairSyncRequest(
            audio_dir=str(self.audio_dir),
            srt_dir=str(self.srt_dir),
            audio_filename="080.mp3",
            srt_filename="80_arabic.srt",
            whisper_model="medium",
            mode="word",
            words_per_sub=2,
            global_offset_ms=25,
            start_padding_ms=50,
            end_padding_ms=100,
            min_duration_ms=500,
            prevent_overlaps=False,
            repetition_mode="duplicate"
        )

        with patch("app.QuranAligner", return_value=aligner):
            result = app.synchronize_bulk_pair(request)

        output_path = self.audio_dir / "80_arabic.srt"
        self.assertEqual(result["output_path"], str(output_path))
        self.assertTrue(output_path.is_file())
        self.assertFalse((self.srt_dir / "corrected").exists())
        self.assertEqual(result["stats"]["alignment_warning"], "Review low-confidence subtitles.")
        self.assertEqual(
            aligner.synchronize.call_args.kwargs,
            {
                "audio_path": str(self.audio_dir / "080.mp3"),
                "srt_entries": entries,
                "mode": "word",
                "words_per_sub": 2,
                "global_offset_ms": 25,
                "start_padding_ms": 50,
                "end_padding_ms": 100,
                "min_duration_ms": 500,
                "prevent_overlaps": False,
                "repetition_mode": "duplicate"
            }
        )


if __name__ == "__main__":
    unittest.main()
