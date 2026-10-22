# v0.2.0 — Fish Audio voice catalogue and RouterAI voice IDs

- Speech uses `fish-audio/drama-3` through RouterAI, with the selected Fish Audio voice ID and native Fish Audio parameters.
- Twenty public Russian voices (ten male and ten female) are ranked by provider use count and installed into gender/use-case folders. See [v0.2.0 notes](RELEASE-v0.2.0.md).
- Speech settings contain a protected API key and optional advanced Fish Audio JSON parameters.
- Optional Stable Audio 3 Medium runs locally for both background music and sound effects. Weights are shared; the controls remain independent.
- Local audio uses an isolated inference worker, CPU offloading, chunks up to 15 seconds and tiled decoding. Downloads and synthesis report progress and support cancellation.
- New API avatars use a Fish voice ID. Existing local recordings and book voice assignments are retained; link a Fish ID before using an older local avatar for RouterAI speech.
- Base setup installs the lightweight desktop/API dependencies. Optional local audio is installed on demand.
- Completed audiobook fragments and dry speech remain available for continued assembly and music mixing.

`tools/build_release.py` creates the allowlisted source ZIP and Windows bootstrap installer. Credentials and private recordings are excluded from the repository and release package. Optional local music inference is not required for the voice catalogue or RouterAI speech.

Use [INSTALL.md](INSTALL.md) to install this source revision. Close the app and back up `data` and `outputs` before updating. See [ROUTERAI.md](ROUTERAI.md) for key/voice-ID configuration and [THIRD_PARTY.md](../THIRD_PARTY.md) for upstream and voice-recording terms.

## Previous release history

### v0.1.1 — installation fixes

- Drive/folder browser and available-space display.
- Package caches and temporary extraction remain in the selected installation folder.
- Resumable model downloads with bounded retries and checksum verification.

These entries describe previous releases.
