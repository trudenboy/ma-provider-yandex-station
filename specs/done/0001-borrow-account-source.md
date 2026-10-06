---
id: "0001"
title: "Borrow the Yandex account from a linked Yandex Music provider"
size: M
status: done
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

A "Yandex account source" dropdown in guided setup lets users pick a configured
Yandex Music instance to borrow its credentials, or keep "Use own credentials". When
borrowing, the provider's own login buttons and token storage are hidden
and unused; Quasar cookies and Glagol device tokens are derived from the
linked instance's x_token / music token, read-only — Yandex Music remains
the only writer and rotator of persisted credentials.

## Acceptance Criteria

1. Guided setup shows a "Yandex account source" dropdown listing
   every configured Yandex Music instance plus "Use own credentials
   (default)"; a stale selection defaults to own when setup is reopened.
   Runtime borrowing remains bound to the selected account and never silently
   switches to another account.
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
6. With "Use own credentials" selected, guided setup offers device-code,
   QR and cookie login; runtime uses the own cascade and own storage.
7. Startup and re-authentication resolve the current owner tokens once through
   `resolve_credentials()`. If the selected owner is missing, startup waits once
   on the domain-ready event and leaves further retries to MA.

## Test Plan

- `tests/test_setup_flow.py` and `tests/test_setup_flow_unit.py` — guided
  account selection, borrowing without local login, and own login methods.
- `TestConfigEntries.test_no_account_source_or_auth_actions` — source selection
  and auth actions live in setup, rather than the provider options surface.
- `test_setup_allows_borrow_without_own_tokens` — `setup()` succeeds with
  empty own tokens when a source instance is selected.
- `TestBorrowInitSession.test_builds_session_from_linked_tokens` — session
  gets the linked x_token/music token; own cascade not invoked; no
  `_update_config_value` calls.
- The remaining `tests/test_borrow_mode.py` cases cover rotated setup-data
  tokens, retryable owner readiness, single token reads, and the read-only
  re-authentication path. `tests/test_provider_cascade.py` covers own mode.
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
 |                    |            |--resolve_credentials->|--get_setup_value-->|
 |                    |            |<-(music,x)-------------|                     |
 |                    |            |  (mint+cache if only x)|                     |
 |                    |            | YandexSession(x, music)|                     |
 |                    |            | login_token() → cookies|                     |
 |                    |            | discover_players()     |                     |
 |     Quasar 401     |            |                        |                     |
 |                    |            |--resolve_credentials->| (current token pair)|
 |                    |            | re-login_token()       |                     |
```
