# PR #5605: review remediation for v1.5.17

Reviewed on 2026-10-03 against upstream head `9a251921891154610a5d2493cbddcade16d6f9a5` and provider v1.5.16. All review threads were fetched with their resolved/outdated flags; pagination was exhausted. The latest review contains two open findings, both from Copilot, with no human replies in those threads.

## Cancellation cleanup

[Finding](https://github.com/music-assistant/server/pull/5605#discussion_r4173750211): cancellation during the pending Glagol send bypasses the existing exception cleanup. Confirmed with actual asyncio task cancellation: the current request retained its external media after the task raised `CancelledError`, on both legacy and audio-client paths.

The existing cleanup handler now also catches `asyncio.CancelledError` and immediately re-raises it after cleanup. Its generation guard is retained, so cancellation of an older request cannot clear a newer successful request. No additional stop command or change to acknowledgement/state handling is introduced.

Regression coverage exercises the real `play_media` method with controllable asynchronous sends: current-request cancellation on both protocols, plus cancellation after a successful replacement. Before the fix, the two current-request cases failed and the replacement case passed. Afterwards all three passed. They also passed with the installed MA API preloaded instead of using the standalone MA stubs. The full suite passed: 181 tests.

## PR description

[Finding](https://github.com/music-assistant/server/pull/5605#discussion_r4173750229): the description still references v1.5.15 while the synced provider is v1.5.16. The replacement paragraph targets the resulting v1.5.17 release, includes WAV defaults and cancellation cleanup, and links to that release's changelog. The existing PR-template sections and checklist are retained.

Replacement paragraph:

Updates the bundled Yandex Station provider from v1.5.1 to v1.5.17 to restore firmware-compatible stream playback, correct linked-account startup and playback state, and reduce startup delay with WAV defaults. Cancelled playback commands now clean up their own state without clearing a newer request; saved codec preferences remain respected. Includes announcement and QR setup fixes with regression coverage; details are in the [provider changelog](https://github.com/trudenboy/ma-provider-yandex-station/blob/v1.5.17/CHANGELOG.md).

## Publication

Provider changes go through a PR to the provider repository's dev branch and its release pipeline. The pipeline synchronizes the provider into the integration and upstream PR branches. The upstream Music Assistant branch is not pushed directly.
