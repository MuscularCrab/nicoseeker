# SPDX-License-Identifier: GPL-3.0-or-later
"""NicoSeeker - Spotify playlist import for Nicotine+.

Adds a /spotify command (and a settings page) that turns a public Spotify
playlist or song link into Soulseek downloads: it fetches the track list with
no API keys, searches the network for each track, ranks the results by quality
and how well they match, and queues the best copy for download.
"""
import threading

from pynicotine.events import events
from pynicotine.pluginsystem import BasePlugin

# Nicotine+ loads a user plugin by executing its __init__.py without first
# registering the package in sys.modules, so relative imports (from .x) fail.
# The loader does append the plugin's own folder to sys.path, so import the
# uniquely-named helper modules absolutely, with a relative fallback for when
# the plugin is imported as a normal package (e.g. tests).
try:
    from ns_matching import Result, build_query, rank
    from ns_spotify import SpotifyError, fetch_playlist, import_csv
except ImportError:  # pragma: no cover - package-style import
    from .ns_matching import Result, build_query, rank
    from .ns_spotify import SpotifyError, fetch_playlist, import_csv

# Nicotine+ 3.3.x delivers a search result's file attributes as a dict keyed
# by these numbers (FileAttribute.BITRATE / DURATION); newer dev builds use an
# object with .bitrate / .length. Support both so the plugin works on either.
_ATTR_BITRATE = 0
_ATTR_DURATION = 1


def _attr(attrs, dict_key, obj_name):
    """Read a file attribute from either a dict or an attributes object."""
    try:
        if isinstance(attrs, dict):
            return int(attrs.get(dict_key) or 0)
        return int(getattr(attrs, obj_name, 0) or 0)
    except (TypeError, ValueError):
        return 0


class Plugin(BasePlugin):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.settings = {
            "auto_download": True,
            "prefer_lossless": True,
            "allow_lower_quality": False,
            "results_wait_seconds": 8,
            "seconds_between_searches": 5,
            "max_sources_per_track": 1,
        }
        self.metasettings = {
            "auto_download": {
                "description": ("Automatically download the best match for "
                                "each track (off = just run the searches)"),
                "type": "bool"
            },
            "prefer_lossless": {
                "description": ("Prefer FLAC/lossless, then 320kbps MP3"),
                "type": "bool"
            },
            "allow_lower_quality": {
                "description": ("Accept lower quality when no lossless / "
                                "320kbps copy is found"),
                "type": "bool"
            },
            "results_wait_seconds": {
                "description": "Seconds to gather search results per track:",
                "type": "int", "minimum": 3, "maximum": 30
            },
            "seconds_between_searches": {
                "description": ("Seconds between searches (higher avoids the "
                                "server's search rate limit on big playlists):"),
                "type": "int", "minimum": 2, "maximum": 30
            },
            "max_sources_per_track": {
                "description": "How many copies to grab per track:",
                "type": "int", "minimum": 1, "maximum": 3
            },
            "close_search_tabs": {
                "description": ("Close each track's search tab once its "
                                "results have been processed"),
                "type": "bool"
            },
        }
        self.settings["close_search_tabs"] = True

        self.commands = {
            "spotify": {
                "callback": self.spotify_command,
                "description": ("Import a Spotify playlist or song and queue "
                                "it for download"),
                "parameters": ["<playlist or song URL>"],
            },
            "spotifycsv": {
                "callback": self.spotify_csv_command,
                "description": "Import a Spotify CSV export (Exportify/chosic)",
                "parameters": ["<path to .csv>"],
            },
        }

        # token -> {"track": Track, "results": [Result, ...]}
        self._pending = {}
        self._queue = []          # remaining Tracks to search
        self._running = False
        self._playlist_name = ""
        # Set to the Track while we call do_search, so the "add-search"
        # event can tell our searches apart from the user's own
        self._expecting = None

    # -------------------------------------------------------- lifecycle

    def loaded_notification(self):
        events.connect("file-search-response", self._on_search_response)
        events.connect("add-search", self._on_add_search)
        self.log("NicoSeeker ready. Use /spotify <playlist or song URL> to "
                 "import a Spotify playlist.")

    def disable(self):
        for name, cb in (("file-search-response", self._on_search_response),
                         ("add-search", self._on_add_search)):
            try:
                events.disconnect(name, cb)
            except Exception:
                pass
        self._running = False
        self._queue = []
        self._pending = {}
        self._expecting = None

    # --------------------------------------------------------- commands

    def spotify_command(self, args, user=None, room=None):
        url = (args or "").strip()
        if not url:
            self.log("Usage: /spotify <Spotify playlist or song URL>")
            return
        if self._running:
            self.log("A Spotify import is already running - let it finish "
                     "first.")
            return
        self.log(f"Fetching Spotify data for {url} ...")
        # Network fetch off the main thread; resume on the main thread
        threading.Thread(target=self._fetch_thread, args=(url, None),
                         daemon=True).start()

    def spotify_csv_command(self, args, user=None, room=None):
        path = (args or "").strip().strip('"')
        if not path:
            self.log("Usage: /spotifycsv <path to exported .csv>")
            return
        if self._running:
            self.log("A Spotify import is already running.")
            return
        self.log(f"Importing CSV {path} ...")
        threading.Thread(target=self._fetch_thread, args=(None, path),
                         daemon=True).start()

    # --------------------------------------------------- import pipeline

    def _fetch_thread(self, url, csv_path):
        try:
            playlist = import_csv(csv_path) if csv_path else fetch_playlist(url)
        except SpotifyError as exc:
            events.invoke_main_thread(self.log, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            events.invoke_main_thread(self.log, f"Could not import: {exc}")
            return
        # Resume on the main thread (all core calls must run there)
        events.invoke_main_thread(self._on_playlist_loaded, playlist)

    def _on_playlist_loaded(self, playlist):
        tracks = list(playlist.tracks)
        if not tracks:
            self.log("No tracks found.")
            return
        self._playlist_name = playlist.name
        self._queue = tracks
        self._running = True
        note = ""
        if getattr(playlist, "maybe_truncated", False):
            note = (" (Spotify's page only exposes the first 100 tracks; use "
                    "/spotifycsv for longer playlists)")
        self.log(f"Loaded '{playlist.name}' - {len(tracks)} track(s){note}. "
                 "Searching...")
        self._search_next()

    def _search_next(self):
        if not self._running or not self._queue:
            if self._running and not self._pending:
                self._running = False
                self.log(f"Finished importing '{self._playlist_name}'.")
            return

        track = self._queue.pop(0)
        query = build_query(track)
        if not query:
            self._schedule_next()
            return

        # The token is captured in _on_add_search, which fires synchronously
        # from do_search. Reading a private attribute (e.g. search._token)
        # breaks across Nicotine+ versions, so we use the public event.
        self._expecting = track
        try:
            self.core.search.do_search(query, "global", switch_page=False)
        except Exception as exc:  # noqa: BLE001
            self.log(f"Search failed for '{track}': {exc}")
            self._schedule_next()
            return
        finally:
            self._expecting = None

        self.log(f"Searching: {track}")
        self._schedule_next()

    def _on_add_search(self, token, search, *_args):
        """Fires for every new search. Only claim the one we just started."""
        if self._expecting is None:
            return
        self._pending[token] = {"track": self._expecting, "results": []}
        wait = int(self.settings["results_wait_seconds"])
        events.schedule(delay=wait, callback=self._collect,
                        callback_args=(token,))

    def _schedule_next(self):
        gap = int(self.settings["seconds_between_searches"])
        events.schedule(delay=gap, callback=self._search_next)

    def _on_search_response(self, msg):
        token = getattr(msg, "token", None)
        bucket = self._pending.get(token)
        if bucket is None:
            return
        username = getattr(msg, "search_username", None) or getattr(
            msg, "username", "")
        free = bool(getattr(msg, "freeulslots", False))
        speed = int(getattr(msg, "ulspeed", 0) or 0)
        queue = int(getattr(msg, "inqueue", 0) or 0)
        for fileinfo in (getattr(msg, "list", None) or []):
            try:
                _code, name, size, _ext, attrs = fileinfo
            except (ValueError, TypeError):
                continue
            bucket["results"].append(Result(
                username=username, path=name, size=int(size or 0),
                bitrate=_attr(attrs, _ATTR_BITRATE, "bitrate"),
                length=_attr(attrs, _ATTR_DURATION, "length"),
                free_slots=free, queue=queue, speed=speed))

    def _collect(self, token):
        bucket = self._pending.pop(token, None)
        if bucket is None:
            return
        track = bucket["track"]
        require_320 = (self.settings["prefer_lossless"]
                       and not self.settings["allow_lower_quality"])
        ranked = rank(track, bucket["results"], require_320=require_320)
        if not ranked and not self.settings["allow_lower_quality"]:
            # Relax the quality gate once before giving up
            ranked = rank(track, bucket["results"], require_320=False)

        if not ranked:
            self.log(f"No match found: {track}")
        elif not self.settings["auto_download"]:
            self.log(f"{track}: {len(ranked)} match(es) found "
                     "(auto-download off)")
        else:
            n = max(1, int(self.settings["max_sources_per_track"]))
            for r in ranked[:n]:
                try:
                    self.core.downloads.enqueue_download(
                        r.username, r.path, size=r.size)
                    self.log(f"Queued: {track}  <-  {r.basename} "
                             f"from {r.username}")
                except Exception as exc:  # noqa: BLE001
                    self.log(f"Could not queue {track}: {exc}")

        # Tidy up the per-track search tab we created
        if self.settings.get("close_search_tabs", True):
            try:
                self.core.search.remove_search(token)
            except Exception:  # noqa: BLE001
                pass

        if self._running and not self._queue and not self._pending:
            self._running = False
            self.log(f"Finished importing '{self._playlist_name}'.")
