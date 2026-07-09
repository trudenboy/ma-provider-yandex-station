---
id: "0001"
title: "Borrow the Yandex account from a linked Yandex Music provider"
size: M
status: inprogress
priority: P1
effort_minutes: 20
feature_id:
---

## Problem Statement

Users who already run the Yandex Music provider must log into Yandex a
second time to use their Stations: the provider carries its own device/QR/
cookies login and stores its own token set. Two token families for one
account also means two independent silent-refresh cascades — and a refresh
token is single-use server-side, so the two copies can invalidate each
other if the user ever seeds them from the same login.

## Solution Summary

A new "Yandex account source" dropdown in the provider settings (same
option the Ynison plugin already offers): pick a configured Yandex Music
instance to borrow its credentials, or keep "Use own credentials". When
borrowing, the provider's own login buttons and token storage are hidden
and unused; Quasar cookies and Glagol device tokens are derived from the
linked instance's x_token / music token, read-only — Yandex Music remains
the only writer and rotator of persisted credentials.

## Acceptance Criteria

1. The settings dialog shows a "Yandex account source" dropdown listing
   every configured Yandex Music instance plus "Use own credentials
   (default)"; a stale selection (instance removed) falls back to own.
2. With a linked instance selected, the provider starts and discovers
   speakers without any provider-local login (setup succeeds with empty
   own-token config).
3. In borrow mode the provider never writes to its own token keys nor to
   the linked instance's config (no rotation, no persistence).
4. When the linked instance is not loaded yet (start-up ordering), setup
   reports a temporary condition and succeeds on retry — not a login
   failure.
5. A Quasar 401 in borrow mode re-derives session cookies from the
   linked instance's current x_token instead of running the own-token
   rotation cascade; when Yandex rejects that x_token the user is told to
   re-authenticate the Yandex Music provider.
6. With "Use own credentials" selected (or nothing configured), behavior
   is byte-identical to today: own login buttons, own cascade, own
   storage.

## Test Plan

- `test_config_entries_account_source_dropdown` — dropdown lists YM
  instances + own sentinel; login actions hidden while borrowing.
- `test_setup_allows_borrow_without_own_tokens` — `setup()` succeeds with
  empty own tokens when a source instance is selected.
- `test_init_session_borrow_builds_session_from_linked_tokens` — session
  gets the linked x_token/music token; own cascade not invoked; no
  `_update_config_value` calls.
- `test_init_session_borrow_ym_not_loaded_is_transient` —
  `ResourceTemporarilyUnavailable` propagates, own tokens untouched.
- `test_silent_reauth_borrow_rereads_linked_tokens` — 401 path refreshes
  cookies from the linked x_token, never calls rotation.
- Manual: live MA with yandex_music configured — select it as source in
  the Station provider, verify discovery + playback with no Station-side
  login.

## Sequence Diagram

```
User        MA config        StationProvider      BorrowedCredentialSource     YM instance
 |  select "YM: Main" |             |                        |                     |
 |------------------->|            |                        |                     |
 |                    | setup()    |                        |                     |
 |                    |----------->| borrow mode            |                     |
 |                    |            |--read_tokens()-------->|--config.get_value-->|
 |                    |            |<-(music,x)-------------|                     |
 |                    |            | resolve_music_token()  |                     |
 |                    |            |  (mint+cache if only x)|                     |
 |                    |            | YandexSession(x, music)|                     |
 |                    |            | login_token() → cookies|                     |
 |                    |            | discover_players()     |                     |
 |     Quasar 401     |            |                        |                     |
 |                    |            |--read_tokens()-------->|  (fresh x_token)    |
 |                    |            | re-login_token()       |                     |
```
