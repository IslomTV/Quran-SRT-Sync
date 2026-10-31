import asyncio
import html
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException

import app
from core.srt_parser import read_srt_file
from fastapi.responses import FileResponse


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

    def test_bulk_page_prefills_srt_directory_from_application_root(self):
        page = asyncio.run(app.serve_index())
        expected_path = html.escape(
            os.path.join(app.CURRENT_DIR, "data", "arabic_srt"),
            quote=True
        )

        self.assertIn(f'value="{expected_path}"', page)
        self.assertNotIn("__DEFAULT_ARABIC_SRT_DIR__", page)
        self.assertNotIn("__DEFAULT_CAPCUT_PROJECTS_DIR__", page)
        self.assertIn('id="capcutProjectsDir"', page)

    def test_main_tool_sections_use_top_tabs_instead_of_collapsed_details(self):
        page = asyncio.run(app.serve_index())

        self.assertIn('role="tablist"', page)
        self.assertIn('id="bulkTab" type="button" role="tab" aria-controls="bulkSection" aria-selected="true" tabindex="0"', page)
        self.assertIn('id="capcutTab"', page)
        self.assertIn('id="generatorTab"', page)
        self.assertIn('role="tabpanel" aria-labelledby="bulkTab"', page)
        self.assertIn('role="tabpanel" aria-labelledby="capcutTab" hidden', page)
        self.assertIn('role="tabpanel" aria-labelledby="generatorTab" hidden', page)
        self.assertIn('<div id="singleSyncWorkflow" hidden class="space-y-4">', page)
        app_script = (Path(app.STATIC_DIR) / "app.js").read_text(encoding="utf-8")
        self.assertIn("singleSyncWorkflow.hidden = sectionTabs[index].id !== 'bulkTab';", app_script)
        self.assertIn("generatorTranslation.value = String(data.default_translation_id);", app_script)
        self.assertNotIn('id="bulkDetails"', page)
        self.assertNotIn('id="capcutDetails"', page)

    def test_favicon_route_serves_svg_asset(self):
        response = asyncio.run(app.serve_favicon())

        self.assertIsInstance(response, FileResponse)
        self.assertEqual(response.media_type, "image/svg+xml")
        self.assertTrue(Path(response.path).is_file())

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
        self.assertEqual(result["output_dir"], str(self.audio_dir / "srt"))

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

    def test_pair_sync_creates_srt_folder_and_saves_arabic_srt_inside(self):
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

        output_path = self.audio_dir / "srt" / "80_arabic.srt"
        self.assertEqual(result["output_path"], str(output_path))
        self.assertTrue(output_path.is_file())
        self.assertTrue((self.audio_dir / "srt").is_dir())
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
