import io
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.quran_generator import QuranGenerator


class TestQuranGenerator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.script_path = Path(self.temp_dir.name) / "quran_srt_generator.py"
        self.script_path.write_text("# test script\n", encoding="utf-8")
        self.generator = QuranGenerator(self.script_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_options_adapt_reciter_and_translation_api_payloads(self):
        module = SimpleNamespace(
            QURANCOM_RECITERS_API="reciters",
            QURANCOM_TRANSLATIONS_API="translations",
            OUTPUT_ROOT=r"C:\Quran",
            DEFAULT_TRANSLATOR_QUERY="Default Translator",
            request_json=lambda url: {
                "recitations": [{"id": 7, "reciter_name": "Mishari", "style": "Murattal"}]
            } if url == "reciters" else {
                "translations": [{"id": 20, "name": "Default Translator", "language_name": "Uzbek"}]
            },
        )

        with patch("core.quran_generator.load_generator_module", return_value=module):
            options = self.generator.options()

        self.assertEqual(options["reciters"], [{"id": 7, "name": "Mishari", "style": "Murattal"}])
        self.assertEqual(
            options["translations"],
            [{"id": 20, "name": "Default Translator", "language": "Uzbek"}],
        )
        self.assertEqual(options["output_root"], r"C:\Quran")
        self.assertEqual(options["default_translation"], "Default Translator")
        self.assertEqual(options["default_translation_id"], 20)

    def test_options_resolves_configured_default_translation_id_exactly(self):
        module = SimpleNamespace(
            QURANCOM_RECITERS_API="reciters",
            QURANCOM_TRANSLATIONS_API="translations",
            OUTPUT_ROOT=r"C:\Quran",
            DEFAULT_TRANSLATOR_QUERY="Default Translator",
            request_json=lambda url: {
                "recitations": [],
            } if url == "reciters" else {
                "translations": [
                    {"id": 19, "name": "Default Translator (Extended)", "language_name": "Uzbek"},
                    {"id": 20, "name": "Default Translator", "language_name": "Uzbek"},
                ]
            },
        )

        with patch("core.quran_generator.load_generator_module", return_value=module):
            options = self.generator.options()

        self.assertEqual(options["default_translation_id"], 20)

    def test_start_runs_script_and_reports_complete_progress(self):
        process = SimpleNamespace(
            stdout=io.StringIO("Processing Surah 2\nTotal ayahs: 7\n"),
            wait=lambda: 0,
        )
        with patch("core.quran_generator.subprocess.Popen", return_value=process) as popen:
            started = self.generator.start(
                surah=2,
                all_surahs=False,
                reciter_id=7,
                translation_id=20,
                download_audio=True,
                clean_translation=False,
                add_numbers=False,
            )
            status = self._wait_for_terminal_status(started["job_id"])

        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["completed"], 1)
        self.assertEqual(status["succeeded"], 1)
        command = popen.call_args.args[0]
        self.assertIn("--surah", command)
        self.assertIn("2", command)
        self.assertIn("--download-audio", command)
        self.assertIn("20", command)
        self.assertIn("--no-clean", command)
        self.assertIn("--no-numbers", command)

    def test_all_surahs_reports_partial_failures(self):
        process = SimpleNamespace(
            stdout=io.StringIO(
                "Processing Surah 1\nTotal ayahs: 7\n"
                "Processing Surah 2\n❌ Surah 2 failed: network unavailable\n"
            ),
            wait=lambda: 0,
        )
        with patch("core.quran_generator.subprocess.Popen", return_value=process):
            started = self.generator.start(
                surah=None,
                all_surahs=True,
                reciter_id=7,
                translation_id=20,
                download_audio=False,
                clean_translation=True,
                add_numbers=True,
            )
            status = self._wait_for_terminal_status(started["job_id"])

        self.assertEqual(status["status"], "partial")
        self.assertEqual(status["total"], 114)
        self.assertEqual(status["completed"], 2)
        self.assertEqual(status["succeeded"], 1)
        self.assertEqual(
            status["failures"],
            [{"surah": 2, "message": "network unavailable"}],
        )

    def test_reports_windows_dll_initialization_failure_when_process_has_no_output(self):
        process = SimpleNamespace(stdout=io.StringIO(""), wait=lambda: 0xC0000142)
        with patch("core.quran_generator.subprocess.Popen", return_value=process):
            started = self.generator.start(
                surah=1,
                all_surahs=False,
                reciter_id=7,
                translation_id=20,
                download_audio=False,
                clean_translation=True,
                add_numbers=True,
            )
            status = self._wait_for_terminal_status(started["job_id"])

        message = (
            "Generator exited with Windows status 0xC0000142 "
            "(DLL initialization failed) before producing output. "
            "Check the Python runtime and its DLL dependencies."
        )
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["failures"][0]["message"], message)
        self.assertEqual(status["log"], [message])

    def test_start_rejects_invalid_surah_selection(self):
        with self.assertRaisesRegex(ValueError, "either one surah or all surahs"):
            self.generator.start(
                surah=None,
                all_surahs=False,
                reciter_id=7,
                translation_id=20,
                download_audio=False,
                clean_translation=True,
                add_numbers=True,
            )
        with self.assertRaisesRegex(ValueError, "1 to 114"):
            self.generator.start(
                surah=115,
                all_surahs=False,
                reciter_id=7,
                translation_id=20,
                download_audio=False,
                clean_translation=True,
                add_numbers=True,
            )

    def _wait_for_terminal_status(self, job_id):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = self.generator.status(job_id)
            if status["status"] in {"completed", "partial", "failed"}:
                return status
            time.sleep(0.01)
        self.fail("Generator job did not reach a terminal status.")


if __name__ == "__main__":
    unittest.main()
