---
id: "0002"
title: "Per-player toggle to stop mirroring Station volume to the intercept target"
size: S
status: done
priority: P2
effort_minutes: 10
feature_id:
---

## Problem Statement

When a Station intercepts native playback (e.g. "Алиса, включи музыку") and
hands it off to another Music Assistant player, every Station volume reading
is copied onto the target player. Users who manage the target's volume from
Music Assistant see their setting overwritten as soon as an intercept starts
and on every later Station volume change
([#202](https://github.com/trudenboy/ma-provider-yandex-station/issues/202)).
There is no way to keep the intercept while leaving the target's volume alone.

## Solution Summary

Add a per-player boolean setting, "Mirror Station volume to intercept target",
next to the existing intercept settings. It is enabled by default, so current
behaviour is unchanged. When disabled, the intercept handoff, track metadata,
pause and seek mirroring keep working, the Station is still muted during the
session and restored afterwards, but no volume command is ever sent to the
target player. Station volume buttons and "Алиса, громче" then only affect
the Station itself.

## Acceptance Criteria

1. Each Station's player settings expose a boolean
   `intercept_mirror_volume` entry with default `True`.
2. With the setting enabled (or never saved), Station volume changes during an
   intercept session are sent to the target exactly as before.
3. With the setting disabled, no volume command reaches the target player
   during an intercept session, including the first tick that starts it.
4. With the setting disabled, the Station is still muted when the session
   starts and its saved volume is still restored when the session ends.
5. With the setting disabled, a user unmuting the Station mid-session still
   updates the saved Station volume, so session end restores the new value.
6. Pause and seek mirroring to the target are unaffected by the setting.

## Test Plan

- `test_volume_mirror_disabled_sends_no_target_volume` — intercept tick with
  the toggle off: intercept starts, `cmd_volume_set` is never awaited.
- `test_volume_mirror_disabled_still_tracks_user_unmute` — toggle off, user
  raises Station volume mid-session: saved baseline and self-mute flag update.
- `test_volume_mirror_defaults_to_enabled_when_unset` — config without the key
  still mirrors volume.
- `test_player_config_entries_include_volume_mirror_toggle` — entry present,
  boolean, default `True`.
- Manual: enable intercept on a Station, turn the toggle off, ask Alice to
  play music, confirm the target keeps its Music Assistant volume.
