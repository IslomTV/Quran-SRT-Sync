"""
Quran SRT Sync - Command Line Interface (CLI)
Automated Quran subtitle synchronization for CapCut and video editing.
"""

import os
import sys
import argparse

# Enable UTF-8 console output for Windows terminals
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Ensure local core imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.srt_parser import read_srt_file, write_srt_file, sec_to_time_str
from core.aligner import QuranAligner
from core.quran_db import detect_surah_from_text


def print_progress(step, total, msg):
    bar_len = 25
    filled = int(round(bar_len * step / total))
    bar = "=" * filled + "-" * (bar_len - filled)
    print(f"[{bar}] Step {step}/{total}: {msg}")


def main():
    parser = argparse.ArgumentParser(
        description="Quran SRT Sync: Automatically synchronize Quran subtitles with recitation audio for CapCut."
    )
    parser.add_argument("-a", "--audio", required=True, help="Path to input audio file (MP3, WAV, M4A, etc.)")
    parser.add_argument("-s", "--srt", required=True, help="Path to input Arabic SRT subtitle file")
    parser.add_argument("-o", "--output", default=None, help="Path to output synchronized SRT file")
    parser.add_argument(
        "-m", "--mode",
        choices=["preserve", "word", "verse"],
        default="preserve",
        help="Synchronization mode (default: preserve existing subtitle segmentation)"
    )
    parser.add_argument(
        "-w", "--words-per-sub",
        type=int,
        default=1,
        help="Number of words per subtitle in 'word' mode (default: 1)"
    )
    parser.add_argument(
        "--model",
        choices=["tiny", "base", "small", "medium"],
        default="small",
        help="Whisper model size (default: small; medium is slower and uses more resources)"
    )
    parser.add_argument("--offset", type=float, default=0.0, help="Global subtitle offset in milliseconds (default: 0.0)")
    parser.add_argument("--start-pad", type=float, default=60.0, help="Start padding in milliseconds (default: 60.0)")
    parser.add_argument("--end-pad", type=float, default=120.0, help="End padding in milliseconds (default: 120.0)")
    parser.add_argument("--min-dur", type=float, default=600.0, help="Minimum subtitle duration in milliseconds (default: 600.0)")
    parser.add_argument(
        "--allow-overlaps",
        action="store_true",
        help="Disable contiguous timing; allow gaps and overlapping timestamps between consecutive subtitles"
    )
    parser.add_argument(
        "--repeat-mode",
        choices=["encompass", "duplicate", "off"],
        default="encompass",
        help="How to handle verses repeated by reciter: 'encompass' (default: keep timestamp covering repetition), 'duplicate', 'off'"
    )

    args = parser.parse_args()

    audio_path = os.path.abspath(args.audio)
    srt_path = os.path.abspath(args.srt)

    if not os.path.exists(audio_path):
        print(f"Error: Audio file not found at '{audio_path}'", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(srt_path):
        print(f"Error: SRT file not found at '{srt_path}'", file=sys.stderr)
        sys.exit(1)

    # Determine output path
    if args.output:
        out_path = os.path.abspath(args.output)
    else:
        base, _ = os.path.splitext(srt_path)
        out_path = f"{base}_synced.srt"

    print("=================================================================")
    print("                QURAN SRT SYNC FOR CAPCUT                        ")
    print("=================================================================")
    print(f" Audio File    : {audio_path}")
    print(f" SRT File      : {srt_path}")
    print(f" Output File   : {out_path}")
    print(f" Sync Mode     : {args.mode}")
    print(f" Whisper Model : {args.model}")
    print(f" Global Offset : {args.offset:+.1f} ms")
    print("-----------------------------------------------------------------")

    # Read SRT
    try:
        entries = read_srt_file(srt_path)
    except Exception as e:
        print(f"Error reading SRT file: {e}", file=sys.stderr)
        sys.exit(1)

    # Detect Surah if possible
    all_text = " ".join(e['text'] for e in entries)
    surah_info = detect_surah_from_text(all_text)
    if surah_info:
        print(f" Detected Surah: #{surah_info['number']} {surah_info['english_name']} ({surah_info['arabic_name']})")
    print(f" Loaded {len(entries)} subtitle entries.")
    print("-----------------------------------------------------------------")

    aligner = QuranAligner(
        whisper_model_name=args.model,
        progress_callback=print_progress
    )

    try:
        result = aligner.synchronize(
            audio_path=audio_path,
            srt_entries=entries,
            mode=args.mode,
            words_per_sub=args.words_per_sub,
            global_offset_ms=args.offset,
            start_padding_ms=args.start_pad,
            end_padding_ms=args.end_pad,
            min_duration_ms=args.min_dur,
            prevent_overlaps=not args.allow_overlaps,
            repetition_mode=args.repeat_mode
        )
    except Exception as e:
        print(f"\nAlignment failed: {e}", file=sys.stderr)
        sys.exit(1)

    synced_entries = result['synced_entries']
    stats = result['stats']

    # Write output SRT
    write_srt_file(out_path, synced_entries)

    print("=================================================================")
    print("                     SYNCHRONIZATION COMPLETE                    ")
    print("=================================================================")
    print(f" Audio Duration     : {stats['audio_duration_sec']:.2f} s")
    print(f" Total Subtitles    : {stats['total_subtitles']}")
    print(f" Pauses Detected    : {stats['num_pauses_detected']}")
    if stats.get('num_repetitions_detected', 0) > 0:
        print(f" Repetitions Caught : {stats['num_repetitions_detected']} (encompassed in subtitle timestamps)")
    print(f" Average Shift (Δt) : {stats['average_shift_sec']:+.3f} s")
    print(f" Max Shift (Δt)     : {stats['max_shift_sec']:+.3f} s")
    if stats.get('alignment_warning'):
        print(f" WARNING            : {stats['alignment_warning']}")
        print(f" Review subtitle(s) : {', '.join(map(str, stats['low_confidence_subtitles']))}")
    print(f" Corrected SRT saved: {out_path}")
    print("=================================================================\n")

    # Print first 5 entries comparison preview
    print("Sample Timings (First 5 Entries):")
    for item in synced_entries[:5]:
        orig = f"{item['orig_start_str']} -> {item['orig_end_str']}"
        sync = f"{item['start_str']} -> {item['end_str']}"
        shift = item.get('shift_sec', 0.0)
        snippet = item['text'].replace('\n', ' ')
        if len(snippet) > 40:
            snippet = snippet[:40] + "..."
        print(f" #{item['index']:02d} [Orig: {orig}] => [Sync: {sync}] (Shift: {shift:+.3f}s) | {snippet}")


if __name__ == '__main__':
    main()
