# Book Studio

**English** · [Русский](README.ru.md)

A Windows desktop studio for reusable voice avatars and multi-voice audiobooks. The application is branded **Vox Studio**.

**Speech uses [RouterAI Drama 3](https://routerai.ru/models/fish-audio/drama-3). Music and sound effects use one optional local Stable Audio 3 Medium model.**

[Installation](docs/INSTALL.md) · [RouterAI configuration](docs/ROUTERAI.md) · [Bundled voices](docs/VOICE-PACK.md) · [Third-party components](THIRD_PARTY.md)

## Start from this source revision

1. Download this branch from GitHub using **Code → Download ZIP**, then extract it to a writable folder.
2. Run `setup.cmd`. It installs private Python 3.12 and the desktop/API dependencies, then creates a shortcut.
3. Open **Speech / RouterAI** (**Озвучка / RouterAI**) and save your RouterAI API key. The speech model is `fish-audio/drama-3`.
4. Choose a bundled avatar, or create one from a 3–30 second recording and enter the exact words spoken in the selected interval.
5. Generate speech in the studio, or import a book, configure its annotation API, and assign narrator and character voices.

This revision is delivered as source. A new Windows installer and source release archive have not been built for this change. Existing installations should back up `data` and `outputs` before updating, then rerun `setup.cmd`.

## What the app does

- Organizes voice avatars into searchable folders and includes [five attributed Russian reference recordings](docs/VOICE-PACK.md). Existing avatar edits, archived voices and book assignments are retained.
- Imports PDF, DOCX, EPUB, FB2, TXT and other supported text formats; appends chapters while retaining character context.
- Separates narration, character dialogue and sound cues. Voices can be assigned to a narrator, category, character or chapter.
- Sends emotional directions and selected voice references through native Fish Audio attributes. Advanced sampling options are available as JSON in speech settings.
- Saves completed audiobook fragments for pause/resume and exports a chapter MP3, a ZIP of chapters, or the whole book as MP3.
- Offers independent **Background music** and **Generate sound effects** checkboxes. Music is mixed quietly under speech; dry speech remains available. Manual sound files, narrator reading and skipped cues retain their priority.
- Shows progress for API requests, downloads, local synthesis and chapter assembly. API synthesis is indeterminate while the provider supplies no percentage.
- Supports Russian and English interface languages. Book text and model prompts are not translated by the interface language.

## Processing

| Task | Backend |
| --- | --- |
| Voice cloning and expressive speech | RouterAI API · Fish Audio Drama 3 |
| Book markup, characters, music cues and number preparation | DeepSeek API by default; OpenRouter or another compatible analysis API can be configured |
| Background music and sound effects | Optional local Stable Audio 3 Medium with shared weights |

Speech needs an internet connection and a RouterAI account/key; a local GPU is only required when using the GPU music/effects option. The analysis API has its own key and billing. New avatars require an exact reference transcript entered by the user; the app does not install a transcription model.

The base setup installs the lightweight dependencies in `requirements-client.txt`. When local music or effects are first requested, or **Prepare music and sound effects** is pressed, the app installs an isolated local runtime and about **10.4 GB of model weights**, with resumable downloads and SHA-256 verification.

For an 8 GB GPU, local audio uses at most 15-second chunks, CPU offloading and tiled decoding. **CPU** can be selected in speech settings if GPU generation cannot be used. This configuration has not been benchmarked on an 8 GB PC for this change. See [installation details](docs/INSTALL.md).

## Privacy and project status

The selected voice sample and speech text are sent to RouterAI. Book annotation sends text and relevant context to the configured analysis provider. Music and effect prompts are processed locally. API keys saved through the interface are encrypted with Windows DPAPI for the current Windows account; personal books, avatars, keys and generated audio are excluded from Git.

Paid speech requests are not retried automatically. After a network failure, resume explicitly: the provider may already have processed the interrupted request. API availability and prices are governed by the provider.

The full application, local synthesis, build and test suite were not run. A separately authorized API preview with a narrator reference returned audio in 5.05 seconds; this is not a full application or GPU memory validation. Use reference recordings and book material you have permission to process. [Third-party terms](THIRD_PARTY.md) apply separately; no application source license has been selected yet.
