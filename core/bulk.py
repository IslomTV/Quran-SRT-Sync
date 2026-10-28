"""Pair audio and Arabic SRT files for bulk synchronization."""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BulkPairing:
    matches: list[tuple[Path, Path]]
    unmatched_audio: list[Path]
    unmatched_srt: list[Path]
    errors: list[str]


def _audio_id(path: Path) -> int | None:
    if path.suffix.lower() != '.mp3' or not path.stem.isdigit():
        return None
    return int(path.stem)


def _srt_id(path: Path) -> int | None:
    match = re.fullmatch(r'(\d+)_arabic', path.stem, re.IGNORECASE)
    return int(match.group(1)) if match else None


def pair_bulk_files(audio_dir: str | Path, srt_dir: str | Path) -> BulkPairing:
    """Pair numeric MP3 names with matching ``<number>_arabic.srt`` files."""
    audio_root = Path(audio_dir)
    srt_root = Path(srt_dir)
    if not audio_root.is_dir():
        raise NotADirectoryError(f"Audio directory not found: {audio_root}")
    if not srt_root.is_dir():
        raise NotADirectoryError(f"SRT directory not found: {srt_root}")

    audio_by_id: dict[int, Path] = {}
    srt_by_id: dict[int, Path] = {}
    duplicate_ids: set[int] = set()
    errors = []
    unmatched_audio = []
    unmatched_srt = []

    for path in sorted(audio_root.iterdir()):
        if not path.is_file() or path.suffix.lower() != '.mp3':
            continue
        file_id = _audio_id(path)
        if file_id is None:
            unmatched_audio.append(path)
            errors.append(f"MP3 filename must be a number, such as 080.mp3: {path.name}")
        elif file_id in audio_by_id:
            duplicate_ids.add(file_id)
            errors.append(
                f"Multiple MP3 files have the same numeric ID {file_id}: "
                f"{audio_by_id[file_id].name}, {path.name}"
            )
        else:
            audio_by_id[file_id] = path

    for path in sorted(srt_root.iterdir()):
        if not path.is_file() or path.suffix.lower() != '.srt':
            continue
        if not path.stem.lower().endswith('_arabic'):
            continue
        file_id = _srt_id(path)
        if file_id is None:
            unmatched_srt.append(path)
            errors.append(f"Arabic SRT filename must be <number>_arabic.srt: {path.name}")
        elif file_id in srt_by_id:
            duplicate_ids.add(file_id)
            errors.append(
                f"Multiple Arabic SRT files have the same numeric ID {file_id}: "
                f"{srt_by_id[file_id].name}, {path.name}"
            )
        else:
            srt_by_id[file_id] = path

    matches = []
    for audio_path in sorted(audio_by_id.values()):
        file_id = _audio_id(audio_path)
        if file_id in srt_by_id and file_id not in duplicate_ids:
            matches.append((audio_path, srt_by_id[file_id]))

    matched_audio = {audio for audio, _ in matches}
    matched_srt = {srt for _, srt in matches}
    unmatched_audio.extend(path for path in audio_by_id.values() if path not in matched_audio)
    unmatched_srt.extend(path for path in srt_by_id.values() if path not in matched_srt)

    for path in sorted(unmatched_audio):
        if _audio_id(path) not in duplicate_ids:
            errors.append(f"No matching Arabic SRT file found for {path.name}")
    for path in sorted(unmatched_srt):
        if _srt_id(path) not in duplicate_ids:
            errors.append(f"No matching MP3 file found for {path.name}")

    return BulkPairing(
        matches=matches,
        unmatched_audio=sorted(set(unmatched_audio)),
        unmatched_srt=sorted(set(unmatched_srt)),
        errors=errors
    )
