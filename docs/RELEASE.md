# v0.2.3 — audiobook MP3 compatibility

- Final chapter and whole-book MP3s use **44.1 kHz stereo, 192 kb/s MPEG-1 Layer III**. This avoids the previous 24 kHz MPEG-2 output, which reduced the requested bitrate to 160 kb/s and could produce MPG123 decoding warnings.
- Existing **24 kHz WAV fragments**, paid-response caches and checkpoints are unchanged. Reassembling the same speech uses those files and needs no new synthesis.
- A real ffmpeg regression test checks the encoded format, clean decoding, duration and reuse of completed speech.

See [v0.2.3 notes](RELEASE-v0.2.3.md) for details and how to rebuild an older MP3.

## Previous release history

### v0.2.2 — parallel audiobook speech and visible checkbox states

- Audiobook speech uses **3 concurrent RouterAI requests** by default. **Speech / RouterAI → Concurrent requests** accepts **1–8**, including sequential operation at 1.
- Each worker has an independent HTTP client. Completed segments are checkpointed separately and assembled in source order. Voice assignments, performance tags and speech cache identities are retained.
- API failures stop new work while submitted successes are saved. Pause drains submitted work; stopping API speech retains completed fragments. Paid requests are not retried automatically.
- Checkboxes have visible borders and check marks, including disabled states. Busy local-model tasks wait with status messages, cancellation and a finite timeout.

See [v0.2.2 notes](RELEASE-v0.2.2.md) for behavior and validation coverage.

### v0.2.1 — visible audio controls and cancellable local-model waiting

- Audiobooks show adjacent **Background music — AI** and **Sound effects — AI** controls above the tabs. The detailed effect control stays synchronized; the studio has a direct button to the book sound panel.
- The audiobook dialog fits a 1110 × 790 window. Accompaniment changes preserve speech checkpoints and annotation.
- Busy local-model locks are waited on with progress and cancellation instead of failing immediately. Real subprocess tests cover contention, timeout, cancellation and crashed owners.
- Music and sound effects continue to share one optional local Stable Audio 3 Medium model.

See [v0.2.1 notes](RELEASE-v0.2.1.md) for behavior and validation details.

### v0.2.0 — Fish Audio voice catalogue and RouterAI voice IDs

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

### v0.1.1 — installation fixes

- Drive/folder browser and available-space display.
- Package caches and temporary extraction remain in the selected installation folder.
- Resumable model downloads with bounded retries and checksum verification.

These entries describe previous releases.
