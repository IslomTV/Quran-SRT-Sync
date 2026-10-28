"""
Quran SRT Sync - SRT Subtitle Parser & Serializer
Handles reading and writing SRT subtitles with full preservation of Quranic Arabic
text, diacritics, formatting, and high-precision millisecond timestamps.
"""

import re
import os


def time_str_to_sec(time_str: str) -> float:
    """Converts 'HH:MM:SS,mmm' or 'HH:MM:SS.mmm' to float seconds."""
    time_str = time_str.strip().replace(',', '.')
    parts = time_str.split(':')
    if len(parts) == 3:
        h = float(parts[0])
        m = float(parts[1])
        s = float(parts[2])
        return h * 3600.0 + m * 60.0 + s
    elif len(parts) == 2:
        m = float(parts[0])
        s = float(parts[1])
        return m * 60.0 + s
    return float(parts[0])


def sec_to_time_str(sec: float) -> str:
    """Converts float seconds to CapCut/standard SRT format 'HH:MM:SS,mmm'."""
    sec = max(0.0, float(sec))
    total_ms = int(round(sec * 1000.0))
    
    ms = total_ms % 1000
    total_sec = total_ms // 1000
    s = total_sec % 60
    total_min = total_sec // 60
    m = total_min % 60
    h = total_min // 60

    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt_content(content: str) -> list[dict]:
    """
    Parses SRT string content into a structured list of subtitle entries.
    Preserves exact text, linebreaks, and diacritics verbatim.
    """
    # Remove BOM if present and normalize line endings
    content = content.replace('\ufeff', '').replace('\r\n', '\n').replace('\r', '\n')

    entries = []
    # Blocks are separated by one or more blank lines
    blocks = re.split(r'\n\s*\n', content.strip())

    for block in blocks:
        lines = [l for l in block.split('\n') if l.strip()]
        if len(lines) < 2:
            continue

        # Look for timestamp line
        ts_line_idx = -1
        ts_match = None
        for i, line in enumerate(lines[:3]):
            m = re.match(
                r'(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})',
                line.strip()
            )
            if m:
                ts_line_idx = i
                ts_match = m
                break

        if ts_match is None:
            continue

        index_str = lines[0].strip() if ts_line_idx > 0 else str(len(entries) + 1)
        start_str = ts_match.group(1).replace('.', ',')
        end_str = ts_match.group(2).replace('.', ',')

        start_sec = time_str_to_sec(start_str)
        end_sec = time_str_to_sec(end_str)

        text_lines = lines[ts_line_idx + 1:]
        text = "\n".join(text_lines).strip()

        entries.append({
            'index': len(entries) + 1,
            'original_index': index_str,
            'start_str': start_str,
            'end_str': end_str,
            'start_sec': round(start_sec, 3),
            'end_sec': round(end_sec, 3),
            'text': text
        })

    return entries


def read_srt_file(file_path: str) -> list[dict]:
    """
    Reads an SRT file with automatic encoding detection.
    Tries UTF-8-sig (handles BOM), UTF-8, CP1256 (Windows Arabic), ISO-8859-6.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"SRT file not found: {file_path}")

    encodings = ['utf-8-sig', 'utf-8', 'cp1256', 'iso-8859-6', 'latin-1']
    content = None

    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                content = f.read()
                # If we read Arabic characters without error, this encoding is valid
                if any('\u0600' <= c <= '\u06FF' for c in content):
                    break
        except (UnicodeDecodeError, Exception):
            continue

    if content is None:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

    return parse_srt_content(content)


def generate_srt_string(entries: list[dict]) -> str:
    """
    Serializes subtitle entries to a clean, CapCut-compliant SRT string.
    Ensures correct 1-based indexing, valid timestamps, and exact Arabic text.
    """
    output_blocks = []
    for i, e in enumerate(entries, start=1):
        start_str = sec_to_time_str(e['start_sec'])
        end_str = sec_to_time_str(e['end_sec'])
        text = e['text'].strip()
        block = f"{i}\n{start_str} --> {end_str}\n{text}"
        output_blocks.append(block)

    return "\n\n".join(output_blocks) + "\n"


def write_srt_file(file_path: str, entries: list[dict]) -> None:
    """Writes subtitle entries to an SRT file in UTF-8 encoding (with BOM for CapCut Windows)."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    content = generate_srt_string(entries)
    # Using utf-8-sig ensures Windows applications like CapCut properly recognize Arabic characters
    with open(file_path, 'w', encoding='utf-8-sig') as f:
        f.write(content)

