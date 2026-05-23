# Spotify

Spotify is an inherited optional toolset for personal media control. It can search, inspect playback, edit playlists, and control Spotify Connect devices through Spotify's Web API.

Spotify is not part of the forecasting core. It should stay disabled unless a profile needs it, and it does not write forecast evidence, assumptions, memories, scores, or calibration lessons. If a forecast workflow ever uses listening-history or media data as evidence, capture that claim explicitly through the forecast ledger with source, timestamp, and rationale.

## Prerequisites

- A Spotify account.
- An active Spotify Connect device for playback control.
- Spotify enabled in the active Superforecasting Agent toolset.
- A lightweight Spotify developer app for OAuth PKCE.

Some playback-mutating actions require Spotify Premium. Read-only search and library operations can still be useful without enabling playback control.

## Setup

Enable the toolset:

```bash
superforecasting-agent tools
```

Toggle Spotify on and save. The inherited `hermes tools` command remains a compatibility alias for migrated installs.

Authenticate:

```bash
superforecasting-agent auth spotify
```

If no `HERMES_SPOTIFY_CLIENT_ID` is configured, the wizard walks through creating a Spotify developer app, saves the client id, then continues into OAuth consent. `HERMES_SPOTIFY_CLIENT_ID` and `HERMES_SPOTIFY_REDIRECT_URI` remain inherited runtime variable names.

New profiles store tokens in:

```text
~/.superforecasting-agent/auth.json
```

Migrated installs may still read:

```text
~/.hermes/auth.json
~/.hermes/.env
```

The active inference provider is not changed by Spotify auth.

## Spotify App Values

When the wizard opens Spotify's developer dashboard, create an app with:

| Field | Value |
|---|---|
| App name | Any local name, for example `superforecasting-agent` |
| App description | Any personal description |
| Website | Leave blank |
| Redirect URI | `http://127.0.0.1:43827/spotify/callback` |
| API | Web API |

Copy the Client ID into the auth wizard. PKCE does not require a client secret.

## Running over SSH / in a headless environment

When running over SSH or in a headless container, the wizard may skip automatic browser open. Copy the printed dashboard and authorization URLs into a browser on your local machine.

If the callback listener is running on the remote host, forward the callback port:

```bash
ssh -N -L 43827:127.0.0.1:43827 user@remote-host
```

For more cases, see [OAuth over SSH / Remote Hosts](../../guides/oauth-over-ssh.md).

## Verify

```bash
superforecasting-agent auth status spotify
```

This reports whether tokens are present and when the access token expires. Refresh is automatic when the Spotify API returns an expired-token response. Re-authenticate if you revoke the app or run:

```bash
superforecasting-agent auth logout spotify
```

## Tool Reference

The toolset exposes these actions when enabled.

### `spotify_playback`

| Action | Purpose |
|---|---|
| `get_state` | Full playback state. |
| `get_currently_playing` | Current track, if any. |
| `recently_played` | Recently played tracks. |
| `play` | Start or resume playback. |
| `pause` | Pause playback. |
| `next` / `previous` | Skip tracks. |
| `seek` | Jump to a position. |
| `set_repeat` | Change repeat mode. |
| `set_shuffle` | Change shuffle mode. |
| `set_volume` | Set volume percentage. |

Playback-mutating actions need an active device and may require Premium.

### `spotify_devices`

| Action | Purpose |
|---|---|
| `list` | List Spotify Connect devices visible to the account. |
| `transfer` | Move playback to a device id. |

### `spotify_queue`

| Action | Purpose |
|---|---|
| `get` | Inspect queued tracks. |
| `add` | Append a track URI to the queue. |

### `spotify_search`

Search the Spotify catalog by query and type.

### `spotify_playlists`

| Action | Purpose |
|---|---|
| `list` | List user playlists. |
| `get` | Fetch one playlist and tracks. |
| `create` | Create a playlist. |
| `add_items` | Add tracks. |
| `remove_items` | Remove tracks. |
| `update_details` | Rename or edit playlist metadata. |

### `spotify_albums`

| Action | Purpose |
|---|---|
| `get` | Fetch album metadata. |
| `tracks` | Fetch album tracks. |

### `spotify_library`

| Action | Purpose |
|---|---|
| `list` | List saved tracks or albums. |
| `save` | Save tracks or albums. |
| `remove` | Remove saved tracks or albums. |

## Cron

Spotify can be used from scheduled jobs when the toolset is enabled:

```bash
superforecasting-agent cron add \
  --name "morning-playlist" \
  "0 7 * * 1-5" \
  "Transfer playback to my kitchen speaker and start my Morning Commute playlist."
```

Cron remains a forecasting feature first. Use it for Spotify only when the profile intentionally includes personal automation. Forecast self-checks, stale-question reviews, evidence refreshes, and calibration reviews should write through the forecast ledger instead of relying on Spotify tool output.

## Troubleshooting

**No active device**: open Spotify on a phone, desktop, web player, or Connect speaker, then retry.

**Invalid redirect URI**: make sure the Spotify app includes `http://127.0.0.1:43827/spotify/callback`, or set the inherited `HERMES_SPOTIFY_REDIRECT_URI` value to the URI you registered.

**Token revoked**: run `superforecasting-agent auth spotify` again.

**Tool not available**: enable Spotify in `superforecasting-agent tools`. Tool schemas stay out of the default forecast profile until the toolset is enabled.

## Stored State

| Location | Contents |
|---|---|
| `~/.superforecasting-agent/auth.json` | Spotify access token, refresh token, expiry, scope, and redirect URI. |
| `~/.superforecasting-agent/.env` | Inherited `HERMES_SPOTIFY_CLIENT_ID` and optional `HERMES_SPOTIFY_REDIRECT_URI`. |
| `~/.hermes/auth.json` | Legacy auth store, readable during migration. |
| `~/.hermes/.env` | Legacy env file, readable during migration. |
