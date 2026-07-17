"""Rank Soulseek search results for a wanted track and build search queries.

Adapted from SpiritSeeker. No third-party dependencies.
"""
from __future__ import annotations

import re

LOSSLESS_EXTS = {"flac", "wav", "ape", "aiff"}
ACCEPTED_EXTS = LOSSLESS_EXTS | {"mp3", "m4a", "ogg", "opus"}

SUSPECT_WORDS = ("remix", "live", "cover", "instrumental", "karaoke",
                 "acoustic", "acapella", "slowed", "reverb", "nightcore",
                 "sped up", "8d audio")


def _tokenize(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1}


def _strip_extras(title: str) -> str:
    t = re.sub(r"\s*[\(\[].*?[\)\]]", "", title)
    t = re.sub(r"\s*(feat\.?|ft\.?|with)\s.*$", "", t, flags=re.IGNORECASE)
    return t.strip() or title


def build_query(track) -> str:
    """A single, focused search query for a track."""
    if not track.artist:
        return track.title.strip()
    primary_artist = re.split(r"[,;]| & | x | X ", track.artist)[0].strip()
    return f"{primary_artist} {_strip_extras(track.title)}".strip()


class Result:
    """A candidate file from a Soulseek search result."""

    __slots__ = ("username", "path", "size", "bitrate", "length",
                 "free_slots", "queue", "speed", "score")

    def __init__(self, username, path, size=0, bitrate=0, length=0,
                 free_slots=False, queue=0, speed=0):
        self.username = username
        self.path = path
        self.size = size
        self.bitrate = bitrate
        self.length = length
        self.free_slots = free_slots
        self.queue = queue
        self.speed = speed
        self.score = 0.0

    @property
    def ext(self) -> str:
        return self.path.rsplit(".", 1)[-1].lower() if "." in self.path else ""

    @property
    def is_lossless(self) -> bool:
        return self.ext in LOSSLESS_EXTS

    @property
    def basename(self) -> str:
        return self.path.replace("\\", "/").rsplit("/", 1)[-1]


def rank(track, results, require_320: bool) -> list:
    """Filter to plausible matches for the track and sort best-first."""
    title_tokens = _tokenize(_strip_extras(track.title))
    artist_tokens = _tokenize(re.split(r"[,;]", track.artist)[0]) \
        if track.artist else set()
    all_artist_tokens = _tokenize(track.artist) if track.artist else set()

    ranked = []
    for r in results:
        if r.ext not in ACCEPTED_EXTS:
            continue
        path_tokens = _tokenize(r.path)

        if title_tokens and not title_tokens.issubset(path_tokens):
            continue
        # At least one credited artist must appear in the path
        if all_artist_tokens and not (all_artist_tokens & path_tokens):
            continue

        base = r.basename.lower()
        if any(w in base and w not in track.title.lower()
               for w in SUSPECT_WORDS):
            continue

        # Quality gate
        if require_320 and not r.is_lossless and r.bitrate and r.bitrate < 320:
            continue
        if require_320 and not r.is_lossless and not r.bitrate and \
                r.ext == "mp3":
            continue

        # Duration sanity check when both sides know it
        if r.length and track.duration_ms:
            if abs(r.length - track.duration_ms / 1000.0) > 15:
                continue

        score = 0.0
        score += 400 if r.ext == "flac" else 0
        score += 250 if r.ext in LOSSLESS_EXTS - {"flac"} else 0
        if not r.is_lossless:
            score += min(r.bitrate, 320)
        if artist_tokens and artist_tokens & path_tokens == artist_tokens:
            score += 150
        score += 100 if r.free_slots else 0
        score += min(r.speed / 1024, 50)
        score -= min(r.queue * 5, 100)
        r.score = score
        ranked.append(r)

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked
