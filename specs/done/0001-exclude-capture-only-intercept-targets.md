---
id: "0001"
title: "Exclude capture-only sources from intercept targets"
size: S
status: done
priority: P1
effort_minutes: 10
---

## Problem Statement

Music Assistant can expose capture-only audio inputs as source players. Selecting one as a
Yandex Station intercept target makes handoff playback fail because a source cannot render media.

## Solution Summary

Only player types that can receive playback are shown as Yandex Station intercept targets. Regular
players remain selectable regardless of individual advertised playback features so queue-routed
targets such as AirPlay and DLNA stay available.

## Acceptance Criteria

1. Capture-only source players do not appear in the intercept-target selector.
2. The current Yandex Station does not appear in its own target selector.
3. Playback-capable players without a `PLAY_MEDIA` feature remain selectable.
4. Available and unavailable playback-capable targets remain selectable.
5. The selector is sorted by player display name.

## Test Plan

- Extend the intercept target-selector unit test with a capture-only source player.
- Run the complete provider test suite and pre-commit checks.
