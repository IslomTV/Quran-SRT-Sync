from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any


GENERATOR_SCRIPT = Path(r"C:\GitHub\quran-subtitle-generator\quran_srt_generator.py")
_SURAH_STARTED = re.compile(r"Processing Surah\s+(\d+)")
_SURAH_FAILED = re.compile(r"Surah\s+(\d+)\s+failed:\s*(.*)")


def load_generator_module(script_path: Path = GENERATOR_SCRIPT) -> ModuleType:
    if not script_path.is_file():
        raise FileNotFoundError(f"Quran subtitle generator not found: {script_path}")
    spec = importlib.util.spec_from_file_location("quran_srt_generator_ui", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load Quran subtitle generator: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QuranGenerator:
    def __init__(self, script_path: Path = GENERATOR_SCRIPT):
        self.script_path = script_path
        self._lock = threading.Lock()
        self._catalog: dict[str, Any] | None = None
        self._catalog_loaded_at = 0.0
        self._job: dict[str, Any] | None = None

    def options(self, force_refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            if (
                self._catalog is not None
                and not force_refresh
                and time.monotonic() - self._catalog_loaded_at < 3600
            ):
                return self._catalog

        module = load_generator_module(self.script_path)
        recitation_data = module.request_json(module.QURANCOM_RECITERS_API)
        translation_data = module.request_json(module.QURANCOM_TRANSLATIONS_API)
        reciters = [
            {
                "id": item.get("id"),
                "name": item.get("reciter_name") or "",
                "style": item.get("style") or "",
            }
            for item in recitation_data.get("recitations", [])
            if isinstance(item, dict) and item.get("id") is not None
        ]
        translations = [
            {
                "id": item.get("id"),
                "name": item.get("name") or "",
                "language": item.get("language_name") or "",
            }
            for item in translation_data.get("translations", [])
            if isinstance(item, dict) and item.get("id") is not None and item.get("name")
        ]
        default_translation = str(module.DEFAULT_TRANSLATOR_QUERY).strip()
        default_translation_match = next(
            (
                translation
                for translation in translations
                if translation["name"].strip().casefold() == default_translation.casefold()
            ),
            None,
        )
        if default_translation_match is None:
            raise RuntimeError(
                f"Configured default translation was not found: {default_translation}"
            )
        result = {
            "reciters": reciters,
            "translations": translations,
            "output_root": str(module.OUTPUT_ROOT),
            "default_translation": default_translation,
            "default_translation_id": default_translation_match["id"],
            "script_path": str(self.script_path),
        }
        with self._lock:
            self._catalog = result
            self._catalog_loaded_at = time.monotonic()
        return result

    def start(
        self,
        *,
        surah: int | None,
        all_surahs: bool,
        reciter_id: int,
        translation_id: int,
        download_audio: bool,
        clean_translation: bool,
        add_numbers: bool,
    ) -> dict[str, Any]:
        if all_surahs == (surah is not None):
            raise ValueError("Choose either one surah or all surahs.")
        if surah is not None and not 1 <= surah <= 114:
            raise ValueError("Surah number must be from 1 to 114.")
        if reciter_id <= 0:
            raise ValueError("Choose a valid reciter.")
        if translation_id <= 0:
            raise ValueError("Choose a translation.")
        if not self.script_path.is_file():
            raise FileNotFoundError(f"Quran subtitle generator not found: {self.script_path}")

        job_id = str(uuid.uuid4())
        total = 114 if all_surahs else 1
        job = {
            "job_id": job_id,
            "status": "queued",
            "total": total,
            "completed": 0,
            "succeeded": 0,
            "current_surah": None,
            "failures": [],
            "log": [],
            "output_root": None,
        }
        with self._lock:
            if self._job and self._job["status"] in {"queued", "running"}:
                raise RuntimeError("A Quran generation job is already running.")
            if self._catalog:
                job["output_root"] = self._catalog["output_root"]
            self._job = job

        arguments = {
            "surah": surah,
            "all_surahs": all_surahs,
            "reciter_id": reciter_id,
            "translation_id": translation_id,
            "download_audio": download_audio,
            "clean_translation": clean_translation,
            "add_numbers": add_numbers,
        }
        threading.Thread(
            target=self._run_job,
            args=(job_id, arguments),
            name=f"quran-generator-{job_id[:8]}",
            daemon=True,
        ).start()
        return self.status(job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if not self._job or self._job["job_id"] != job_id:
                raise KeyError("Generation job not found.")
            return {**self._job, "failures": list(self._job["failures"]), "log": list(self._job["log"])}

    def _append_log(self, job_id: str, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        with self._lock:
            job = self._job
            if not job or job["job_id"] != job_id:
                return
            job["log"].append(line)
            job["log"] = job["log"][-500:]
            started = _SURAH_STARTED.search(line)
            if started:
                job["current_surah"] = int(started.group(1))
            failed = _SURAH_FAILED.search(line)
            if failed:
                number = int(failed.group(1))
                job["failures"].append({"surah": number, "message": failed.group(2)})
                job["completed"] = min(job["total"], job["completed"] + 1)
            elif "Total ayahs:" in line:
                job["succeeded"] += 1
                job["completed"] = min(job["total"], job["completed"] + 1)

    def _run_job(self, job_id: str, arguments: dict[str, Any]) -> None:
        with self._lock:
            if not self._job or self._job["job_id"] != job_id:
                return
            self._job["status"] = "running"
        command = [sys.executable, "-u", str(self.script_path)]
        if arguments["all_surahs"]:
            command.append("--all")
        else:
            command.extend(["--surah", str(arguments["surah"])])
        command.extend(["--reciter", str(arguments["reciter_id"])])
        command.extend(["--translation", str(arguments["translation_id"])])
        if arguments["download_audio"]:
            command.append("--download-audio")
        if not arguments["clean_translation"]:
            command.append("--no-clean")
        if not arguments["add_numbers"]:
            command.append("--no-numbers")

        environment = dict(os.environ)
        environment["PYTHONIOENCODING"] = "utf-8"
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.script_path.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=environment,
            )
            if process.stdout is None:
                raise RuntimeError("Could not read generator output.")
            for line in process.stdout:
                self._append_log(job_id, line)
            return_code = process.wait()
        except Exception as error:
            with self._lock:
                if self._job and self._job["job_id"] == job_id:
                    self._job["failures"].append(
                        {"surah": self._job["current_surah"], "message": str(error)}
                    )
                    self._job["status"] = "failed"
                    self._job["log"].append(f"Generation failed: {error}")
            return

        with self._lock:
            if not self._job or self._job["job_id"] != job_id:
                return
            job = self._job
            if return_code != 0 and not job["failures"]:
                if (return_code & 0xFFFFFFFF) == 0xC0000142:
                    failure_message = (
                        "Generator exited with Windows status 0xC0000142 "
                        "(DLL initialization failed) before producing output. "
                        "Check the Python runtime and its DLL dependencies."
                    )
                else:
                    failure_message = f"Generator exited with code {return_code}."
                job["failures"].append(
                    {
                        "surah": job["current_surah"],
                        "message": failure_message,
                    }
                )
                if not job["log"]:
                    job["log"].append(failure_message)
            if job["completed"] < job["total"] and not job["failures"]:
                job["failures"].append(
                    {"surah": job["current_surah"], "message": "Generator ended before all requested surahs completed."}
                )
            if job["failures"] and job["succeeded"]:
                job["status"] = "partial"
            elif job["failures"]:
                job["status"] = "failed"
            else:
                job["status"] = "completed"
            job["current_surah"] = None
