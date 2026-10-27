---
id: "0004"
title: "Show the Station's own track as a Yandex Music item"
size: S
status: done
priority: P2
effort_minutes: 10
feature_id:
---

## Problem Statement

When the Station plays on its own (music Alice was asked for, the Yandex app), Music
Assistant shows only the reported title and artist. The track's URI is the bare Yandex
Music id, so:

- "Add to favorites" on the player cannot resolve it. The core then searches the
  library by title and artist, which can like a different track or fail.
- The player shows no cover art, although every report carries one.

The provider already knows which Yandex Music provider instance shares the Station's
account when it borrows that instance's credentials.

## Solution Summary

While the Station plays its own content and the provider borrows the credentials of a
linked Yandex Music instance, the player reports the current track as an item of that
instance: URI `<instance_id>://track/<track id>` with media type track, so the core's
"add currently playing to favorites" adds it straight to that account. The cover from
the report is shown in every mode. With the provider's own login no instance is known
to share the account, so the URI stays the bare id and favorites keep the core's search
fallback. Music Assistant streams are unchanged.

## Acceptance Criteria

1. With a linked Yandex Music instance, a report of the Station's own track `138389651`
   sets the player's current media URI to `<instance_id>://track/138389651` and its
   media type to track.
2. A track id with an album suffix (`12345:678`) yields `<instance_id>://track/12345`.
3. With the provider's own login, or a linked instance that is not loaded, the URI is
   the reported id and the media type stays unknown.
4. The cover URI the Station reports is turned into an `https://` image URL with a
   concrete size and set as the current media image.
5. While a Music Assistant stream plays, the current media is still the requested MA
   item (URI, title, image) and no report replaces it.
6. `players/add_currently_playing_to_favorites` on a Station playing its own track
   resolves the URI to the linked instance's item instead of searching by title.

## Test Plan

- Unit: a report with `playerState.id` and `extra.coverURI`, provider in borrowed mode
  with a loaded linked instance; assert URI, media type and image URL (1, 2, 4).
- Unit: same report in own-login mode and with the linked instance missing (3).
- Unit: confirmed MA stream plus a report; current media stays the MA item (5).
- Manual on HAOS: "Алиса, включи музыку", check the player in MA shows cover art and
  the heart adds the track to Yandex Music favorites of the linked account (6). Confirm
  the exact `coverURI` format from the debug log before relying on it.

## Out of scope

- `PlayerSource.account_id`: nothing in the core reads it yet, and reading the uid from
  another provider's internals is outside this provider's domain.
- Moving the Station's own playback into the MA queue (separate feature).
- Play counts or history for the Station's own playback: Music Assistant tracks only
  its own playback (music-assistant/support#1129).
