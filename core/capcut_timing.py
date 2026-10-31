"""Match numbered Arabic SRT files to CapCut projects and update timings."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SRT_NAME = re.compile(r"^(?P<number>\d+)_arabic\.srt$", re.IGNORECASE)
PROJECT_NAME = re.compile(r"^(?P<number>\d+)\.")
TIMESTAMP = re.compile(
    r"^(?P<start>\d+:\d{2}:\d{2}[,.]\d{1,3})\s+-->\s+"
    r"(?P<end>\d+:\d{2}:\d{2}[,.]\d{1,3})(?:\s+.*)?$"
)


@dataclass(frozen=True)
class Subtitle:
    start: int
    end: int
    text: str


@dataclass
class CapCutSubtitle:
    start: int
    end: int
    text: str
    track_index: int
    segment_index: int


@dataclass
class ProjectPlan:
    number: str
    srt_path: Path
    project_path: Path
    draft_path: Path
    srt_subtitles: list[Subtitle]
    capcut_subtitles: list[CapCutSubtitle]
    mapping: list[tuple[int, tuple[int, ...]]]
    ambiguous_matches: dict[int, tuple[tuple[int, ...], ...]]
    warnings: list[str]
    blockers: list[str]
    extend_duration_to: int | None
    srt_hash: str
    draft_hash: str

    @property
    def eligible(self) -> bool:
        return bool(self.mapping) and not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "srt_filename": self.srt_path.name,
            "project_name": self.project_path.name,
            "subtitle_counts": {
                "srt": len(self.srt_subtitles),
                "capcut": len(self.capcut_subtitles),
                "matched": len(self.mapping),
                "matched_capcut_clips": sum(
                    len(capcut_indices) for _, capcut_indices in self.mapping
                ),
                "split_groups": sum(
                    len(capcut_indices) > 1 for _, capcut_indices in self.mapping
                ),
            },
            "matches": [
                {
                    "srt_index": srt_index + 1,
                    "capcut_index": capcut_indices[0] + 1,
                    "capcut_indices": [index + 1 for index in capcut_indices],
                    "split_count": len(capcut_indices),
                    "start": self.srt_subtitles[srt_index].start,
                    "end": self.srt_subtitles[srt_index].end,
                    "text": self.srt_subtitles[srt_index].text,
                }
                for srt_index, capcut_indices in self.mapping
            ],
            "unmatched_srt": [
                {
                    "index": index + 1,
                    "text": self.srt_subtitles[index].text,
                }
                for index in range(len(self.srt_subtitles))
                if index not in {item[0] for item in self.mapping}
            ],
            "ambiguous_matches": [
                {
                    "srt_index": srt_index + 1,
                    "text": self.srt_subtitles[srt_index].text,
                    "candidates": [
                        [capcut_index + 1 for capcut_index in group]
                        for group in groups
                    ],
                }
                for srt_index, groups in self.ambiguous_matches.items()
            ],
            "unmatched_capcut": [
                {
                    "index": index + 1,
                    "text": self.capcut_subtitles[index].text,
                    "start": self.capcut_subtitles[index].start,
                    "end": self.capcut_subtitles[index].end,
                }
                for index in range(len(self.capcut_subtitles))
                if index not in {
                    capcut_index
                    for _, capcut_indices in self.mapping
                    for capcut_index in capcut_indices
                }
            ],
            "warnings": self.warnings,
            "blockers": self.blockers,
            "eligible": self.eligible,
        }


@dataclass
class Preview:
    plans: dict[str, ProjectPlan]
    files: dict[Path, str]
    issues: list[str]

    def to_dict(self, preview_id: str) -> dict[str, Any]:
        projects = [plan.to_dict() for plan in self.plans.values()]
        eligible = sum(plan.eligible for plan in self.plans.values())
        return {
            "preview_id": preview_id,
            "projects": projects,
            "issues": self.issues,
            "summary": {
                "pairs": len(projects),
                "eligible": eligible,
                "blocked": len(projects) - eligible,
                "issues": len(self.issues),
            },
        }


def parse_timestamp(value: str) -> int:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    whole_seconds, milliseconds = seconds.split(".")
    return (
        (int(hours) * 3600 + int(minutes) * 60 + int(whole_seconds)) * 1_000_000
        + int(milliseconds.ljust(3, "0")) * 1_000
    )


def parse_srt(path: Path) -> list[Subtitle]:
    content = path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
    subtitles: list[Subtitle] = []
    for block_number, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            raise ValueError(f"{path.name}: block {block_number} has no timing line")
        match = TIMESTAMP.fullmatch(lines[timing_index].strip())
        if match is None:
            raise ValueError(f"{path.name}: invalid timing in block {block_number}")
        start = parse_timestamp(match.group("start"))
        end = parse_timestamp(match.group("end"))
        if end <= start:
            raise ValueError(f"{path.name}: block {block_number} has invalid duration")
        text = "\n".join(lines[timing_index + 1 :]).strip()
        if not text:
            raise ValueError(f"{path.name}: block {block_number} has empty text")
        subtitles.append(Subtitle(start, end, text))
    if not subtitles:
        raise ValueError(f"{path.name}: no subtitle entries found")
    return subtitles


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    letters: list[str] = []
    for char in normalized:
        if char == "\u0640" or unicodedata.category(char).startswith("M"):
            continue
        if char == "\u0671":
            char = "\u0627"
        if char.isalpha():
            letters.append(char)
    return "".join(letters)


def load_capcut_subtitles(data: dict[str, Any]) -> list[CapCutSubtitle]:
    materials = data.get("materials")
    if not isinstance(materials, dict) or not isinstance(materials.get("texts"), list):
        raise ValueError("project is missing materials.texts")
    material_by_id = {
        item.get("id"): item
        for item in materials["texts"]
        if isinstance(item, dict) and item.get("id") is not None
    }
    tracks = data.get("tracks")
    if not isinstance(tracks, list):
        raise ValueError("project is missing tracks")

    subtitles: list[CapCutSubtitle] = []
    for track_index, track in enumerate(tracks):
        if not isinstance(track, dict) or track.get("type") != "text":
            continue
        for segment_index, segment in enumerate(track.get("segments", [])):
            if not isinstance(segment, dict):
                continue
            material = material_by_id.get(segment.get("material_id"))
            if not isinstance(material, dict) or material.get("type") != "subtitle":
                continue
            content = material.get("content")
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"subtitle material {material.get('id')} has invalid content JSON"
                    ) from error
            if not isinstance(content, dict) or not isinstance(content.get("text"), str):
                raise ValueError(f"subtitle material {material.get('id')} has no text field")
            timerange = segment.get("target_timerange")
            if not isinstance(timerange, dict):
                raise ValueError("subtitle segment has no target_timerange")
            try:
                start = int(timerange["start"])
                duration = int(timerange["duration"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("subtitle segment has invalid timing") from error
            if duration <= 0:
                raise ValueError("subtitle segment has non-positive duration")
            subtitles.append(
                CapCutSubtitle(
                    start=start,
                    end=start + duration,
                    text=content["text"],
                    track_index=track_index,
                    segment_index=segment_index,
                )
            )
    return sorted(
        subtitles,
        key=lambda item: (item.start, item.track_index, item.segment_index),
    )


def _match_subtitles(
    srt_subtitles: list[Subtitle], capcut_subtitles: list[CapCutSubtitle]
) -> tuple[
    list[tuple[int, tuple[int, ...]]],
    list[int],
    list[int],
    dict[int, tuple[tuple[int, ...], ...]],
]:
    normalized_capcut = [normalize_text(item.text) for item in capcut_subtitles]
    mapping: list[tuple[int, tuple[int, ...]]] = []
    unmatched_srt: list[int] = []
    ambiguous_srt: list[int] = []
    ambiguous_matches: dict[int, tuple[tuple[int, ...], ...]] = {}
    next_capcut_index = 0

    for srt_index, subtitle in enumerate(srt_subtitles):
        normalized = normalize_text(subtitle.text)
        candidates: list[tuple[int, ...]] = []
        if normalized:
            for start_index in range(next_capcut_index, len(capcut_subtitles)):
                combined = ""
                group: list[int] = []
                previous: CapCutSubtitle | None = None
                for end_index in range(start_index, len(capcut_subtitles)):
                    current = capcut_subtitles[end_index]
                    if previous is not None and (
                        current.track_index != previous.track_index
                        or current.segment_index != previous.segment_index + 1
                    ):
                        break
                    group.append(end_index)
                    combined += normalized_capcut[end_index]
                    if combined == normalized:
                        candidates.append(tuple(group))
                    if len(combined) >= len(normalized):
                        break
                    previous = current

        if not candidates:
            unmatched_srt.append(srt_index)
            continue
        if len(candidates) > 1:
            unmatched_srt.append(srt_index)
            ambiguous_srt.append(srt_index)
            ambiguous_matches[srt_index] = tuple(candidates)
            continue
        group = candidates[0]
        mapping.append((srt_index, group))
        next_capcut_index = group[-1] + 1

    used_capcut = {
        capcut_index
        for _, group in mapping
        for capcut_index in group
    }
    return (
        mapping,
        [i for i in range(len(capcut_subtitles)) if i not in used_capcut],
        ambiguous_srt,
        ambiguous_matches,
    )


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_time(microseconds: int) -> str:
    milliseconds = microseconds // 1_000
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"


def _build_plan(
    number: str,
    srt_path: Path,
    project_path: Path,
    allow_overlaps: bool,
    extend_project_duration: bool,
) -> ProjectPlan:
    draft_path = project_path / "draft_content.json"
    if not draft_path.is_file():
        raise ValueError("draft_content.json not found")
    data = json.loads(draft_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("project JSON root is not an object")

    srt_subtitles = parse_srt(srt_path)
    capcut_subtitles = load_capcut_subtitles(data)
    if not capcut_subtitles:
        raise ValueError("project has no subtitle clips on text tracks")
    mapping, unmatched_capcut, ambiguous_srt, ambiguous_matches = _match_subtitles(
        srt_subtitles, capcut_subtitles
    )
    unmatched_srt = [
        index for index in range(len(srt_subtitles))
        if index not in {item[0] for item in mapping}
    ]
    warnings: list[str] = []
    blockers: list[str] = []

    if (project_path / ".locked").exists():
        blockers.append(
            "CapCut project is currently open or locked; close it and preview again before applying"
        )

    if unmatched_srt:
        blockers.append(
            "subtitle text did not match uniquely: "
            + ", ".join(f"SRT #{index + 1}" for index in unmatched_srt)
        )
    if ambiguous_srt:
        blockers.append(
            "multiple CapCut clip groups match: "
            + ", ".join(f"SRT #{index + 1}" for index in ambiguous_srt)
        )
    if unmatched_capcut:
        extras = "; ".join(
            f"CapCut #{index + 1}: {capcut_subtitles[index].text}"
            for index in unmatched_capcut
        )
        warnings.append("unmatched CapCut clips remain unchanged: " + extras)

    for position in range(1, len(srt_subtitles)):
        previous = srt_subtitles[position - 1]
        current = srt_subtitles[position]
        if current.start < previous.end:
            warning = (
                f"SRT #{position + 1} overlaps SRT #{position} by "
                f"{format_time(previous.end - current.start)}"
            )
            warnings.append(warning)
            if not allow_overlaps:
                blockers.append(warning + "; enable the overlap option to proceed")
        elif current.start > previous.end:
            warnings.append(
                f"gap between SRT #{position} and #{position + 1}: "
                f"{format_time(current.start - previous.end)}"
            )

    for srt_index, _capcut_indices in mapping:
        subtitle = srt_subtitles[srt_index]
        for extra_index in unmatched_capcut:
            extra = capcut_subtitles[extra_index]
            if subtitle.start < extra.end and extra.start < subtitle.end:
                warning = (
                    f"SRT #{srt_index + 1} ({format_time(subtitle.start)} to "
                    f"{format_time(subtitle.end)}) overlaps unmatched CapCut "
                    f"#{extra_index + 1} ({format_time(extra.start)} to "
                    f"{format_time(extra.end)}): {extra.text}"
                )
                warnings.append(warning)
                if not allow_overlaps:
                    blockers.append(warning + "; enable the overlap option to proceed")

    extend_duration_to = None
    max_srt_end = max(item.end for item in srt_subtitles)
    try:
        project_duration = int(data["duration"])
    except (KeyError, TypeError, ValueError):
        project_duration = None
    if project_duration is None:
        blockers.append("could not verify project duration")
    elif max_srt_end > project_duration:
        warning = (
            f"last SRT subtitle ends at {format_time(max_srt_end)}, beyond project "
            f"duration {format_time(project_duration)}"
        )
        warnings.append(warning)
        if extend_project_duration:
            extend_duration_to = max_srt_end
        else:
            blockers.append(warning + "; enable project duration extension to proceed")

    return ProjectPlan(
        number=number,
        srt_path=srt_path,
        project_path=project_path,
        draft_path=draft_path,
        srt_subtitles=srt_subtitles,
        capcut_subtitles=capcut_subtitles,
        mapping=mapping,
        ambiguous_matches=ambiguous_matches,
        warnings=warnings,
        blockers=blockers,
        extend_duration_to=extend_duration_to,
        srt_hash=_fingerprint(srt_path),
        draft_hash=_fingerprint(draft_path),
    )


def create_preview(
    srt_directory: str | Path,
    projects_directory: str | Path,
    allow_overlaps: bool = True,
    extend_project_duration: bool = True,
) -> Preview:
    srt_root = Path(srt_directory).expanduser().resolve()
    projects_root = Path(projects_directory).expanduser().resolve()
    if not srt_root.is_dir():
        raise NotADirectoryError(f"SRT directory not found: {srt_root}")
    if not projects_root.is_dir():
        raise NotADirectoryError(f"CapCut projects directory not found: {projects_root}")

    projects: dict[str, list[Path]] = {}
    for path in projects_root.iterdir():
        match = PROJECT_NAME.match(path.name) if path.is_dir() else None
        if match:
            projects.setdefault(match.group("number"), []).append(path)

    srts: dict[str, list[Path]] = {}
    for path in srt_root.iterdir():
        match = SRT_NAME.fullmatch(path.name) if path.is_file() else None
        if match:
            srts.setdefault(match.group("number"), []).append(path)

    plans: dict[str, ProjectPlan] = {}
    issues: list[str] = []
    for number, project_paths in sorted(projects.items(), key=lambda item: min(item[1]).name):
        if len(project_paths) != 1:
            names = ", ".join(path.name for path in sorted(project_paths))
            issues.append(
                f"ambiguous CapCut project folders beginning with {number}: {names}"
            )
            continue
        project_path = project_paths[0]
        candidates = srts.get(number, [])
        if len(candidates) != 1:
            if not candidates:
                issues.append(
                    f"{project_path.name}: no matching Arabic SRT file beginning with {number}"
                )
            else:
                names = ", ".join(path.name for path in sorted(candidates))
                issues.append(
                    f"{project_path.name}: ambiguous Arabic SRT files beginning with "
                    f"{number}: {names}"
                )
            continue
        srt_path = candidates[0]
        try:
            plan = _build_plan(
                number,
                srt_path,
                project_path,
                allow_overlaps,
                extend_project_duration,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            issues.append(f"{project_path.name} -> {srt_path.name}: {error}")
            continue
        plans[number] = plan

    files = {
        path: digest
        for plan in plans.values()
        for path, digest in (
            (plan.srt_path, plan.srt_hash),
            (plan.draft_path, plan.draft_hash),
        )
    }
    return Preview(plans=plans, files=files, issues=issues)


def resolve_ambiguous_matches(
    preview: Preview,
    resolutions: list[tuple[str, int, tuple[int, ...]]],
) -> None:
    """Apply user-selected exact candidates to an existing read-only preview."""
    validated: list[tuple[str, int, tuple[int, ...]]] = []
    selected_entries: set[tuple[str, int]] = set()
    claimed_indices: dict[str, set[int]] = {
        number: {
            capcut_index
            for _, group in plan.mapping
            for capcut_index in group
        }
        for number, plan in preview.plans.items()
    }
    for number, srt_number, capcut_numbers in resolutions:
        plan = preview.plans.get(number)
        if plan is None:
            raise ValueError(f"project {number!r} is not in this preview")
        srt_index = srt_number - 1
        key = (number, srt_index)
        if key in selected_entries:
            raise ValueError(f"SRT #{srt_number} was resolved more than once")
        candidates = plan.ambiguous_matches.get(srt_index)
        if candidates is None:
            raise ValueError(f"SRT #{srt_number} is not an unresolved ambiguous match")
        group = tuple(index - 1 for index in capcut_numbers)
        if group not in candidates:
            raise ValueError(
                f"CapCut group {capcut_numbers!r} is not a candidate for "
                f"project {number}, SRT #{srt_number}"
            )
        if any(index in claimed_indices[number] for index in group):
            raise ValueError(f"CapCut group {capcut_numbers!r} is already assigned")
        selected_entries.add(key)
        claimed_indices[number].update(group)
        validated.append((number, srt_index, group))

    for number, srt_index, group in validated:
        plan = preview.plans[number]
        plan.mapping.append((srt_index, group))
        plan.mapping.sort(key=lambda item: item[0])
        del plan.ambiguous_matches[srt_index]

    for number in {number for number, _, _ in validated}:
        plan = preview.plans[number]
        plan.blockers = [
            blocker
            for blocker in plan.blockers
            if not blocker.startswith(
                ("subtitle text did not match uniquely:", "multiple CapCut clip groups match:")
            )
        ]
        matched_srt = {srt_index for srt_index, _ in plan.mapping}
        unmatched_srt = [
            index for index in range(len(plan.srt_subtitles)) if index not in matched_srt
        ]
        if unmatched_srt:
            plan.blockers.append(
                "subtitle text did not match uniquely: "
                + ", ".join(f"SRT #{index + 1}" for index in unmatched_srt)
            )
        if plan.ambiguous_matches:
            plan.blockers.append(
                "multiple CapCut clip groups match: "
                + ", ".join(
                    f"SRT #{index + 1}" for index in sorted(plan.ambiguous_matches)
                )
            )


def files_unchanged(preview: Preview) -> bool:
    try:
        return all(path.is_file() and _fingerprint(path) == digest for path, digest in preview.files.items())
    except OSError:
        return False


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp:
            temp_path = temp.name
            json.dump(data, temp, ensure_ascii=False, indent=2)
            temp.write("\n")
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass


def apply_preview(preview: Preview, selected_numbers: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not files_unchanged(preview):
        raise RuntimeError("SRT or CapCut files changed since preview; scan again before applying")
    if not selected_numbers:
        raise ValueError("Select at least one eligible project")
    if len(set(selected_numbers)) != len(selected_numbers):
        raise ValueError("Duplicate project selections are not allowed")
    unknown = set(selected_numbers) - set(preview.plans)
    if unknown:
        raise ValueError("Unknown project selection: " + ", ".join(sorted(unknown)))
    ineligible = [
        number for number in selected_numbers if not preview.plans[number].eligible
    ]
    if ineligible:
        raise ValueError(
            "Cannot apply blocked projects: " + ", ".join(sorted(ineligible))
        )

    updated: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for number in selected_numbers:
        plan = preview.plans[number]
        try:
            if (plan.project_path / ".locked").exists():
                raise RuntimeError(
                    "CapCut project is currently open or locked; close it and preview again"
                )
            data = json.loads(plan.draft_path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("project JSON root is not an object")
            current_subtitles = load_capcut_subtitles(data)
            for srt_index, capcut_indices in plan.mapping:
                subtitle = plan.srt_subtitles[srt_index]
                group = [current_subtitles[index] for index in capcut_indices]
                old_start = group[0].start
                old_end = group[-1].end
                if old_end <= old_start:
                    raise ValueError(
                        f"CapCut split group for SRT #{srt_index + 1} has invalid timing"
                    )
                old_span = old_end - old_start
                new_span = subtitle.end - subtitle.start
                for position, capcut_subtitle in enumerate(group):
                    segment = data["tracks"][capcut_subtitle.track_index]["segments"][
                        capcut_subtitle.segment_index
                    ]
                    timerange = segment["target_timerange"]
                    scaled_start = subtitle.start + round(
                        (capcut_subtitle.start - old_start) * new_span / old_span
                    )
                    scaled_end = subtitle.start + round(
                        (capcut_subtitle.end - old_start) * new_span / old_span
                    )
                    if position == 0:
                        scaled_start = subtitle.start
                    if position == len(group) - 1:
                        scaled_end = subtitle.end
                    if scaled_end <= scaled_start:
                        raise ValueError(
                            f"rescaling CapCut split group for SRT #{srt_index + 1} "
                            "would produce a zero-length clip"
                        )
                    timerange["start"] = scaled_start
                    timerange["duration"] = scaled_end - scaled_start
            if plan.extend_duration_to is not None:
                data["duration"] = plan.extend_duration_to

            _atomic_write(plan.draft_path, data)
        except OSError as error:
            errors.append({
                "number": number,
                "project_name": plan.project_path.name,
                "message": str(error),
            })
        except RuntimeError as error:
            errors.append({
                "number": number,
                "project_name": plan.project_path.name,
                "message": str(error),
            })
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            errors.append({
                "number": number,
                "project_name": plan.project_path.name,
                "message": f"could not safely update project: {error}",
            })
        else:
            updated.append({
                "number": number,
                "project_name": plan.project_path.name,
                "updated_subtitles": len(plan.mapping),
                "updated_clips": sum(
                    len(capcut_indices) for _, capcut_indices in plan.mapping
                ),
                "draft_path": str(plan.draft_path),
            })
    return {"updated": updated, "errors": errors}
