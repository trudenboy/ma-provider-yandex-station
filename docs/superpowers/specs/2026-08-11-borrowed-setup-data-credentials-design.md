# Borrowed credentials and development runtime consistency

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

The repository dependency declarations will be aligned on
`ya-passport-auth[ma]==1.8.0` and `segno==1.6.6`. Both packages are runtime
dependencies because the provider imports them in production. `pyproject.toml`,
`provider/manifest.json`, and `uv.lock` must describe the same set and versions.

The guided setup flow will retain its runtime behavior while replacing
untyped third-party return propagation with explicit, checked types so strict
mypy passes.

The standalone setup script will distinguish a valid Music Assistant checkout
from a merely existing directory. An empty invalid `ma-server/` directory may
be removed and cloned automatically; a non-empty invalid directory must be
preserved and reported with an actionable error.

The Linux development Compose environment will use host networking. Published
port mappings will be removed because they are incompatible and redundant with
`network_mode: host`. This lets Music Assistant participate directly in LAN
mDNS and advertise a host-reachable stream-server address.

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
3. Verify dependency declarations and lock data agree on
   `ya-passport-auth[ma]==1.8.0` and `segno==1.6.6`.
4. Exercise the setup script's valid, empty-invalid, and non-empty-invalid
   checkout decisions without deleting user content.
5. Run the targeted borrow tests, full pytest suite, Ruff, mypy and pre-commit.
6. Validate the Compose model, recreate the Docker container, and verify Yandex
   Station passes credential bootstrap and proceeds into discovery on the host
   network.

## Out of scope

This change does not alter production Music Assistant networking or Yandex
Station discovery logic. Host networking applies only to the repository's
Linux development Compose environment.
