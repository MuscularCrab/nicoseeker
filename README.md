# NicoSeeker — Spotify Playlist Import for Nicotine+

A plugin for [Nicotine+](https://nicotine-plus.org/) (the Soulseek client) that
turns a **public Spotify playlist or song link into Soulseek downloads** — no
Spotify account and no API keys required.

Type `/spotify <link>` in Nicotine+ and NicoSeeker will:

1. **Fetch the track list** from Spotify's public pages (keyless).
2. **Search Soulseek** for each track.
3. **Rank the results** by audio quality (FLAC/lossless first, then 320kbps
   MP3) and how well the filename matches the artist and title.
4. **Queue the best copy** for download.

It reuses the matching logic from
[SpiritSeeker](https://github.com/MuscularCrab/spiritseeker), packaged as a
clean, dependency-free Nicotine+ plugin.

## Why a plugin (and not a custom build)?

Nicotine+ is a GTK application whose official Windows builds come from a heavy
MSYS2/GTK toolchain. Rather than fork and re-package the whole app, NicoSeeker
ships as a **drop-in plugin** so you keep using the official, up-to-date
Nicotine+ and simply add this feature. No custom executable to trust or
maintain.

## Install

1. Install Nicotine+ from [nicotine-plus.org](https://nicotine-plus.org/) (or
   your package manager) and sign in to Soulseek.
2. Download **`nicoseeker.zip`** from the
   [latest release](../../releases/latest) and unzip it into your Nicotine+
   user plugins folder. The zip contains a single `nicoseeker/` folder, so it
   drops straight in.

   > Don't use GitHub's green "Code → Download ZIP" / the auto-generated
   > source archives: those unpack as `nicoseeker-<version>/` with the plugin
   > nested inside, which Nicotine+ won't detect as a plugin.

   Plugins folder:

   | OS | Plugins folder |
   |----|----------------|
   | Windows | `%APPDATA%\nicotine\plugins\` |
   | Linux | `~/.local/share/nicotine/plugins/` |
   | macOS | `~/Library/Application Support/nicotine/plugins/` |

   The result should be `…/plugins/nicoseeker/__init__.py`.
3. In Nicotine+, open **Preferences → Plugins**, find **“NicoSeeker — Spotify
   Playlist Import”**, and enable it.

## Use

In any chat or the command box, type:

```
/spotify https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
/spotify https://open.spotify.com/track/2AMysGXOe0zzZJMtH3Nizb
```

For playlists longer than 100 tracks (Spotify's public pages only expose the
first 100), export a CSV with [Exportify](https://exportify.net) or
[chosic.com](https://www.chosic.com/spotify-playlist-exporter/) and run:

```
/spotifycsv C:\path\to\playlist.csv
```

Progress is printed to the Nicotine+ log, and matched tracks are queued in your
**Downloads**.

## Settings

**Preferences → Plugins → NicoSeeker:**

- **Automatically download the best match** — off = just run the searches.
- **Prefer FLAC/lossless, then 320kbps MP3.**
- **Accept lower quality** when no lossless/320kbps copy is found.
- **Seconds to gather results per track** (default 8).
- **Seconds between searches** (default 5) — higher avoids the Soulseek
  server's search rate limit on big playlists.
- **Copies per track** (1–3).

## Notes & limitations

- Searches are paced to avoid the Soulseek server's rate limiting; a large
  playlist takes a while by design.
- NicoSeeker adds a **command and a settings page**, not a new GUI tab —
  Nicotine+'s plugin API doesn't allow adding tabs. A true in-window tab would
  require forking the Nicotine+ GUI and a custom build.
- Only downloads music you're entitled to. This tool searches files shared by
  other Soulseek users; respect copyright law in your country.

## License

[GPL-3.0-or-later](LICENSE) — matching Nicotine+, since this plugin runs inside
it and uses its API.
