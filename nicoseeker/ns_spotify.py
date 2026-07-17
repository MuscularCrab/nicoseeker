"""Fetch public Spotify playlists/tracks with no API keys and no third-party
dependencies (stdlib urllib only, so it works inside the Nicotine+ runtime).

Spotify's embed page (open.spotify.com/embed/playlist/<id>) ships the data as
JSON in a __NEXT_DATA__ script tag. Public playlists need no auth. The embed
exposes at most ~100 tracks, so a CSV export (Exportify / chosic.com) is also
supported for longer playlists.
"""
from __future__ import annotations

import csv
import json
import re
import urllib.request
from dataclasses import dataclass

EMBED_URL = "https://open.spotify.com/embed/{kind}/{item_id}"
EMBED_TRACK_LIMIT = 100

_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class SpotifyError(Exception):
    pass


@dataclass
class Track:
    title: str
    artist: str
    duration_ms: int = 0
    album: str = ""

    def __str__(self):
        return f"{self.artist} - {self.title}" if self.artist else self.title


@dataclass
class Playlist:
    name: str
    tracks: list
    maybe_truncated: bool = False


def parse_spotify_url(url_or_id: str):
    """Return ("playlist"|"track", id) from a URL, spotify: URI, or bare id."""
    text = url_or_id.strip()
    m = re.search(r"(playlist|track)[/:]([A-Za-z0-9]{16,})", text)
    if m:
        return m.group(1), m.group(2)
    if re.fullmatch(r"[A-Za-z0-9]{16,}", text):
        return "playlist", text
    raise SpotifyError(
        "That doesn't look like a Spotify playlist or song link. Expected "
        "something like https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")


def _http_get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})

    # Nicotine+'s bundled runtime ships CA certificates, so the default SSL
    # context works there (Nicotine+ itself uses bare urlopen for HTTPS).
    # In other Python environments the default trust store may be missing,
    # so fall back to certifi's bundle if available. Verification is never
    # disabled.
    contexts = [None]
    try:
        import ssl
        import certifi
        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:  # noqa: BLE001
        pass

    last_exc = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=ctx) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    raise SpotifyError(f"Could not reach Spotify: {last_exc}") from last_exc


def _fetch_embed_entity(kind: str, item_id: str, timeout: int) -> dict:
    html = _http_get(EMBED_URL.format(kind=kind, item_id=item_id), timeout)
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.DOTALL)
    if not m:
        raise SpotifyError(
            f"Could not find {kind} data in the Spotify page - Spotify may "
            "have changed their site. Try a CSV export instead.")
    try:
        data = json.loads(m.group(1))
        return data["props"]["pageProps"]["state"]["data"]["entity"]
    except (ValueError, KeyError, TypeError) as exc:
        raise SpotifyError(
            f"Spotify page layout changed ({exc}). Try a CSV export.") from exc


def fetch_playlist(url_or_id: str, timeout: int = 20) -> Playlist:
    """Fetch a playlist OR a single track depending on the link."""
    kind, item_id = parse_spotify_url(url_or_id)
    entity = _fetch_embed_entity(kind, item_id, timeout)

    if kind == "track":
        title = (entity.get("title") or entity.get("name") or "").strip()
        artist = ", ".join(
            a.get("name", "") for a in entity.get("artists") or []).strip()
        if not title:
            raise SpotifyError("Could not read the song's details from Spotify.")
        track = Track(title=title, artist=artist,
                      duration_ms=int(entity.get("duration") or 0))
        return Playlist(name=str(track), tracks=[track])

    name = entity.get("name") or "Spotify Playlist"
    track_list = entity.get("trackList") or []
    if not track_list:
        raise SpotifyError("The playlist appears to be empty or private.")

    tracks = []
    for item in track_list:
        title = (item.get("title") or "").strip()
        artist = (item.get("subtitle") or "").replace(chr(0xa0), " ").strip()
        if not title:
            continue
        tracks.append(Track(title=title, artist=artist,
                            duration_ms=int(item.get("duration") or 0)))

    return Playlist(name=name, tracks=tracks,
                    maybe_truncated=len(tracks) >= EMBED_TRACK_LIMIT)


def import_csv(path: str) -> Playlist:
    """Import an Exportify / chosic.com CSV export."""
    tracks = []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = {(k or "").lower().strip(): k for k in
                      (reader.fieldnames or [])}

            def col(*names):
                for n in names:
                    if n in fields:
                        return fields[n]
                return None

            title_c = col("track name", "title", "name", "song")
            artist_c = col("artist name(s)", "artist name", "artist",
                           "artists")
            album_c = col("album name", "album")
            dur_c = col("duration (ms)", "duration ms", "duration")
            if not title_c:
                raise SpotifyError(
                    "CSV has no recognizable track-name column.")
            for row in reader:
                title = (row.get(title_c) or "").strip()
                if not title:
                    continue
                artist = (row.get(artist_c) or "").strip() if artist_c else ""
                album = (row.get(album_c) or "").strip() if album_c else ""
                dur = 0
                if dur_c and (row.get(dur_c) or "").strip().isdigit():
                    dur = int(row[dur_c])
                tracks.append(Track(title=title, artist=artist, album=album,
                                    duration_ms=dur))
    except OSError as exc:
        raise SpotifyError(f"Could not read the CSV: {exc}") from exc
    if not tracks:
        raise SpotifyError("No tracks found in that CSV.")
    import os
    return Playlist(name=os.path.basename(path), tracks=tracks)
