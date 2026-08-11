# Borrowed setup-data credentials compatibility

## Problem

Music Assistant's guided setup flow stores Yandex Music credentials in the
provider's encrypted `setup_data`. The shared `BorrowedCredentialSource` in
`ya-passport-auth==1.8.0` reads only regular config values, so it reports that
the linked provider has no credentials and Yandex Station stops before device
discovery.

## Design

Add a private Yandex Station compatibility adapter around
`BorrowedCredentialSource`. It will preserve the shared implementation's
provider validation and legacy config lookup. When that lookup returns no
tokens, the adapter will read `token` and `x_token` through the linked
provider's public `get_setup_value()` API.

The adapter remains read-only: Yandex Music continues to be the only component
that persists or rotates its credentials. If neither storage mechanism has
credentials, existing error handling remains unchanged.

## Compatibility

- Current Music Assistant: credentials are read from encrypted `setup_data`.
- Older Music Assistant/provider versions: regular config values remain the
  fallback through the shared implementation.
- A future `ya-passport-auth` release that supports setup data remains
  compatible because its successful result wins before the local fallback.

## Test plan

1. Add a regression test whose linked Yandex Music provider exposes tokens only
   through `get_setup_value()` and verify borrowed session initialization.
2. Keep the existing legacy-config borrow test to protect backward
   compatibility.
3. Run the targeted borrow tests, full pytest suite, Ruff, mypy and pre-commit.
4. Recreate the Docker container and verify Yandex Station passes credential
   bootstrap and proceeds into discovery.

## Out of scope

This change does not alter Docker networking. LAN mDNS discovery and the
stream-server publish address will be evaluated separately after authentication
bootstrap succeeds.
