# PR #5605: playback request ordering

Draft for maintainer review; publish after the provider fix is merged, released,
and synchronized into the upstream PR.

[Finding](https://github.com/music-assistant/server/pull/5605#discussion_r4196660175).

Playback now claims its generation before awaiting the stream URL and checks it
again before building or sending the command. A slow older resolution is dropped
after a newer play request, pause, or stop. Existing acknowledgement and
cancellation cleanup guards remain in place.

Regression tests cover both playback protocols and pause/stop during resolution.
All four cases failed before their fixes and pass afterward, including with the
installed Music Assistant player classes preloaded.
