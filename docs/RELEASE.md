# Current source change: RouterAI speech and local audio

- Speech uses `fish-audio/drama-3` through RouterAI, with selected avatar references and native Fish Audio parameters.
- Speech settings contain a protected API key and optional advanced Fish Audio JSON parameters.
- Optional Stable Audio 3 Medium runs locally for both background music and sound effects. Weights are shared; the controls remain independent.
- Local audio uses an isolated inference worker, CPU offloading, chunks up to 15 seconds and tiled decoding. Downloads and synthesis report progress and support cancellation.
- New avatars use a user-entered exact reference transcript. Existing avatars, bundled reference recordings and book voice assignments are retained.
- Base setup installs the lightweight desktop/API dependencies. Optional local audio is installed on demand.
- Completed audiobook fragments and dry speech remain available for continued assembly and music mixing.

**Delivery: GitHub source only.** No new Windows EXE, source release archive or version tag was built for this change. The full application, test suite, local inference and model installation were not run. A separately authorized API preview with a 15.4-second narrator reference returned audio in 5.05 seconds for a 174-character directed script; this does not verify the complete desktop workflow or local GPU memory use. Credentials and private recordings are excluded from the repository.

Use [INSTALL.md](INSTALL.md) to install this source revision. Close the app and back up `data` and `outputs` before updating. See [ROUTERAI.md](ROUTERAI.md) for key/reference configuration and [THIRD_PARTY.md](../THIRD_PARTY.md) for upstream and voice-recording terms.

## Previous release history

### v0.1.1 — installation fixes

- Drive/folder browser and available-space display.
- Package caches and temporary extraction remain in the selected installation folder.
- Resumable model downloads with bounded retries and checksum verification.

These historical notes do not identify a newly built release for the current source change.
