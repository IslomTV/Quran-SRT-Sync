"""
Quran SRT Sync - Arabic & Quranic Text Normalizer
Authoritative text is preserved verbatim for output.
This normalizer is used strictly for matching, alignment, and phonetic distance calculations.
"""

import re
import unicodedata
from difflib import SequenceMatcher

# Unicode ranges for Quranic marks, pauses, and signs
# 0600-0605: Arabic subtitle marks, verse markers
# 06D6-06ED: Small high ligatures, stop/waqf signs (sajdah, rub-el-hizb, etc.)
# FD3E, FD3F: Ornate parentheses ﴾ ﴿
QURANIC_SIGNS_REGEX = re.compile(
    r'[\u0600-\u060F\u06D6-\u06ED\uFD3E\uFD3F\u0653-\u0655\u0670\u06DF-\u06E8]'
)

# Harakat / Tashkeel diacritics
# Fathatan, Dammatan, Kasratan, Fatha, Damma, Kasra, Shaddah, Sukun, Tatweel
TASHKEEL_REGEX = re.compile(r'[\u064B-\u0652\u0640]')

# Digits (Arabic-Indic and Western)
DIGITS_AND_PUNCT_REGEX = re.compile(
    r'[\d\u0660-\u0669\u06F0-\u06F9\(\)\[\]\{\}«»"\'\.\,\;\:\-\–\—\؟\!]'
)

# Phonetic consonant substitution mapping for Quranic recitation vs ASR confusions
# In Quranic recitation, tajweed transformations (idgham, ikhfa, tafkheem, tarqeeq)
# and general ASR confusion matrices often swap these phonemes.
PHONETIC_CANONICAL_MAP = {
    'ة': 'ه',
    'ى': 'ي',
    'إ': 'ا',
    'أ': 'ا',
    'آ': 'ا',
    'ٱ': 'ا',
    'ء': 'ا',
    'ئ': 'ي',
    'ؤ': 'و',
    'ص': 'س',  # Tafkheem/Tarqeeq variation
    'ض': 'د',  # Common ASR confusion
    'ط': 'ت',  # Emphatic vs plain stop
    'ظ': 'ز',  # Emphatic vs plain sibilant
    'ذ': 'ز',  # Interdental vs dental
    'ث': 'س',  # Interdental vs dental
    'ق': 'ك',  # Uvular vs velar stop
}


def strip_tashkeel(text: str) -> str:
    """Removes all Arabic short vowel diacritics (Harakat) and tatweel."""
    if not text:
        return ""
    text = TASHKEEL_REGEX.sub('', text)
    text = QURANIC_SIGNS_REGEX.sub('', text)
    return text


def normalize_arabic(text: str, canonical_phonetics: bool = False) -> str:
    """
    Normalizes Arabic text for alignment purposes.
    - Strips tashkeel and Quranic waqf/pause marks.
    - Normalizes alif forms (إ, أ, آ, ٱ -> ا).
    - Normalizes ta marbuta (ة -> ه).
    - Normalizes alif maqsura (ى -> ي).
    - Normalizes hamza forms.
    - Strips punctuation and verse numbers.
    - Collapses whitespace.
    """
    if not text:
        return ""

    # Remove BOM and zero-width characters
    text = text.replace('\ufeff', '').replace('\u200b', '').replace('\u200c', '').replace('\u200d', '')

    # Remove Quranic signs and waqf marks
    text = QURANIC_SIGNS_REGEX.sub('', text)

    # Remove Tashkeel and tatweel
    text = TASHKEEL_REGEX.sub('', text)

    # Remove digits and punctuation
    text = DIGITS_AND_PUNCT_REGEX.sub(' ', text)

    # Normalize Alif variants to plain Alif
    text = re.sub(r'[إأآٱ]', 'ا', text)

    # Normalize Taa Marbuta
    text = re.sub(r'ة', 'ه', text)

    # Normalize Alif Maqsura
    text = re.sub(r'ى', 'ي', text)

    # Normalize Hamza variants
    text = re.sub(r'[ؤ]', 'و', text)
    text = re.sub(r'[ئ]', 'ي', text)
    text = re.sub(r'[ء]', '', text)

    if canonical_phonetics:
        # Extra phonetic collapsing for fuzzy matching against Whisper ASR output
        chars = [PHONETIC_CANONICAL_MAP.get(c, c) for c in text]
        text = "".join(chars)

    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def get_phonetic_skeleton(word: str) -> str:
    """
    Converts a normalized Arabic word into a phonetic consonant skeleton.
    Useful for scoring fuzzy phonetic matches when ASR slightly misrecognizes tajweed.
    """
    norm = normalize_arabic(word, canonical_phonetics=True)
    # Filter non-Arabic letters
    return "".join(c for c in norm if '\u0600' <= c <= '\u06FF')


def arabic_phonetic_similarity(word1: str, word2: str) -> float:
    """
    Computes a similarity score between 0.0 and 1.0 between two Arabic words.
    Handles:
    - Exact match (1.0)
    - Normalized match (0.95)
    - Phonetic skeleton match (0.85)
    - Levenshtein character similarity
    """
    if not word1 or not word2:
        return 0.0

    if word1 == word2:
        return 1.0

    n1 = normalize_arabic(word1)
    n2 = normalize_arabic(word2)

    if n1 == n2:
        return 0.95

    # Check prefix/suffix stripping (e.g. waw conjunction 'و' attached to word)
    if n1.startswith('و') and n1[1:] == n2:
        return 0.90
    if n2.startswith('و') and n2[1:] == n1:
        return 0.90

    # Check 'ال' definite article difference
    if n1.startswith('ال') and n1[2:] == n2:
        return 0.88
    if n2.startswith('ال') and n2[2:] == n1:
        return 0.88

    # Phonetic skeletons
    sk1 = get_phonetic_skeleton(n1)
    sk2 = get_phonetic_skeleton(n2)

    if sk1 == sk2 and len(sk1) >= 2:
        return 0.85

    # Character sequence ratio
    ratio = SequenceMatcher(None, sk1, sk2).ratio()
    return ratio


def tokenize_with_spans(text: str):
    """
    Tokenizes text into words while keeping track of:
    - original raw word token
    - normalized word token
    - phonetic skeleton
    - start and end character positions in the original text
    """
    tokens = []
    # Match contiguous non-whitespace words
    for m in re.finditer(r'\S+', text):
        raw_word = m.group(0)
        norm_word = normalize_arabic(raw_word)
        if norm_word:  # keep tokens that contain Arabic content
            tokens.append({
                'raw': raw_word,
                'norm': norm_word,
                'phonetic': get_phonetic_skeleton(norm_word),
                'char_start': m.start(),
                'char_end': m.end()
            })
    return tokens

