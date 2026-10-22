# Book Studio

**English** · [Русский](README.ru.md)

A Windows desktop studio for reusable voice avatars and multi-voice audiobooks. The application is branded **Vox Studio**.

**Speech uses [RouterAI Drama 3](https://routerai.ru/models/fish-audio/drama-3). Music and sound effects use one optional local Stable Audio 3 Medium model.**

[Installation](docs/INSTALL.md) · [RouterAI configuration](docs/ROUTERAI.md) · [Bundled voices](docs/VOICE-PACK.md) · [Third-party components](THIRD_PARTY.md)

## Start from this source revision

1. Download this branch from GitHub using **Code → Download ZIP**, then extract it to a writable folder.
2. Run `setup.cmd`. It installs private Python 3.12 and the desktop/API dependencies, then creates a shortcut.
3. Open **Speech / RouterAI** (**Озвучка / RouterAI**) and save your RouterAI API key. The speech model is `fish-audio/drama-3`.
4. Choose a Fish Audio catalog voice, or add an avatar with your own Fish Audio voice ID. Create custom voices on Fish Audio first and copy the 32-character ID from the share link.
5. Generate speech in the studio, or import a book, configure its annotation API, and assign narrator and character voices.

Release source archives and Windows installers are built with `tools/build_release.py`. Existing installations should back up `data` and `outputs` before updating, then rerun `setup.cmd` in the same installation folder.

## What the app does

- Organizes Fish Audio catalog voices into searchable folders and retains [legacy Russian reference recordings](docs/VOICE-PACK.md). Existing avatar edits, archived voices and book assignments are retained.
- Imports PDF, DOCX, EPUB, FB2, TXT and other supported text formats; appends chapters while retaining character context.
- Separates narration, character dialogue and sound cues. Voices can be assigned to a narrator, category, character or chapter.
- Sends emotional directions in the text and the selected Fish Audio voice ID to RouterAI. Additional provider options are available as JSON in speech settings; unsupported options may be ignored by RouterAI.
- Saves completed audiobook fragments for pause/resume and exports a chapter MP3, a ZIP of chapters, or the whole book as MP3.
- Runs audiobook speech with **3 concurrent RouterAI requests** by default, configurable from **1–8** in **Speech / RouterAI**. Completed fragments are saved independently and assembled in original order; paid requests are not retried automatically.
- Shows independent **Background music — AI** and **Sound effects — AI** checkboxes together above the audiobook tabs. **Book music and sound effects** opens the detailed sound panel from the studio. Music is mixed quietly under speech; dry speech remains available. Manual sound files, narrator reading and skipped cues retain their priority.
- Shows progress for API requests, downloads, local synthesis and chapter assembly. API synthesis is indeterminate while the provider supplies no percentage.
- Supports Russian and English interface languages. Book text and model prompts are not translated by the interface language.

## Processing

| Task | Backend |
| --- | --- |
| Expressive speech using Fish Audio voice IDs | RouterAI API · Fish Audio Drama 3 |
| Book markup, characters, music cues and number preparation | DeepSeek API by default; OpenRouter or another compatible analysis API can be configured |
| Background music and sound effects | Optional local Stable Audio 3 Medium with shared weights |

Speech needs an internet connection and a RouterAI account/key; a local GPU is only required when using the GPU music/effects option. The analysis API has its own key and billing. Local recordings are not cloned through RouterAI: create the voice on Fish Audio and link its ID to the avatar. Catalog voices require no recording or transcript.

The base setup installs the lightweight dependencies in `requirements-client.txt`. When local music or effects are first requested, or **Prepare music and sound effects** is pressed, the app installs an isolated local runtime and about **10.4 GB of model weights**, with resumable downloads and SHA-256 verification.

For an 8 GB GPU, local audio uses at most 15-second chunks, CPU offloading and tiled decoding. **CPU** can be selected in speech settings if GPU generation cannot be used. This configuration has not been benchmarked on an 8 GB PC for this change. See [installation details](docs/INSTALL.md).

## Privacy and project status

The selected Fish Audio voice ID and speech text are sent to RouterAI. Book annotation sends text and relevant context to the configured analysis provider. Music and effect prompts are processed locally. API keys saved through the interface are encrypted with Windows DPAPI for the current Windows account; personal books, avatars, keys and generated audio are excluded from Git.

Paid speech requests are not retried automatically. After a network failure, resume explicitly: the provider may already have processed the interrupted request. API availability and prices are governed by the provider.

The RouterAI backend has offline transport, audio decoding and cache tests; current validation details are recorded in [release notes](docs/RELEASE.md). Use voices and book material you have permission to process. [Third-party terms](THIRD_PARTY.md) apply separately; no application source license has been selected yet.
