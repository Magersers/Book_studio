# Drama 3 on an SSH GPU server

Book Studio can synthesize studio recordings and audiobook fragments on a Linux
GPU server using Fish Audio Drama 3. Existing avatars, character assignments,
chapter exports and saved book checkpoints are reused. Speech and analysis are
separate settings: book analysis still uses the selected local model or API.

## Connect

1. Open **Озвучка / SSH-сервер** in the sidebar.
2. Choose **Drama 3 · SSH-сервер**.
3. Paste an OpenSSH command, for example `ssh root@gpu.example.org -p 2222`,
   or a URI such as `ssh://root@gpu.example.org:2222`.
4. Select your private key file, or leave it empty to use your OpenSSH agent/config.
   A key specified with `-i "path with spaces"` in the command is also accepted.
   Encrypted keys must already be unlocked in ssh-agent; password prompts are
   disabled. Arbitrary SSH options and remote shell commands are rejected.
5. Click **Установить / запустить Drama 3**. For an already running compatible
   server, **Проверить подключение** is sufficient.
   To install the optional soundtrack model too, select **Фоновая музыка**.
6. After successful verification, click **Сохранить**. The next speech job uses
   the server. You can switch back to the installed local engine in this dialog.

The connection is tested asynchronously. Download progress shows actual bytes;
package installation and model loading show an activity indicator. Cancel stops
the current installation and retains resumable model `.part` files. Saving is
enabled only after verifying the currently entered address/key/music choice.

## Server requirements and installation

Use Linux with Python 3.12+, an NVIDIA GPU with at least 22 GiB VRAM (RTX 3090
24 GB tested), at least 48 GiB RAM (64 GB recommended), driver 580+ for CUDA 13,
and approximately 55 GB free SSD for a fresh installation. Python's pip or an
existing uv executable must be available. Internet access to GitHub, PyPI,
download.pytorch.org and Hugging Face is required. Installing the large weights
also incurs the server provider's storage/traffic charges.

The installer uses `/workspace/book-studio-drama3`, its own Python environment,
and ComfyUI listening on **127.0.0.1:8187**. It does not change system Python or
other ComfyUI installations. A compatible running ComfyUI on port 8187 or 8188
is reused; no duplicate weights are downloaded. The server keeps running after
closing the desktop app. Connect/install starts an existing managed runtime
again after a server restart. Logs: `setup.log` and `server.log` in that directory.

Pinned components:

| Component | Revision |
| --- | --- |
| ComfyUI v0.42.0 | `355cd6b14c92c19ac3188fe528e47a3f21ef5178` |
| ComfyUI-Drama3 | `67a733a96890637dc27b1914974ad00c569405fb` |
| PyTorch / torchaudio / torchvision | `2.11.0 / 2.11.0 / 0.26.0`, CUDA 13.0 wheels |
| Drama 3 weights and codec | `PedroMarinhoDev/Drama-3-ComfyUI@681e2fae64af1f12e64b9c19c82930a5f3bba1a4` |
| Qwen3-ASR 0.6B | `PedroMarinhoDev/Qwen3-ASR-ComfyUI@6ad8c9be026925839479a8d97749068a4202fbe9` |
| Optional Stable Audio 3 Medium + T5Gemma encoder | `Comfy-Org/stable-audio-3@75aad8836271cb5a5123fb58304fae5d3bb4b0f9` |

The FP8 expert model (38.58 GB), codec (1.57 GB) and ASR (1.56 GB) are downloaded
with fixed byte sizes and SHA-256 checks in `drama3_server_setup.py`. Experts stay
in RAM with a 14 GB GPU cache, matching the tested 24 GB setup. Runtime code is
downloaded at immutable Git revisions. No model files or SSH credentials ship in
the source archive.

## Optional quiet background music

The separate **Фоновая музыка** checkbox is off by default and is available in
SSH mode in server settings, the speech studio, and each book. Server setup
downloads Stable Audio 3 Medium (9.22 GB) and its T5Gemma text encoder (1.19 GB)
only when requested. Allow about 11 GB additional SSD space. Speech and music
run sequentially on the same server; a second GPU is unnecessary. Both downloads
show byte progress, use resumable partial files, and verify SHA-256 hashes.

For normal use, enable the checkbox and click **Озвучить главу** or
**Озвучить книгу**. Planning, model installation when needed, scene music
generation, timing, quiet mixing and the final export run automatically.
No external editor, manual timecodes or separate music assembly are required.

In the short-text studio, the app makes a sparse ambient bed after speech.
For books, the selected DeepSeek/API analysis provider plans scene boundaries
and suggests available avatars for unassigned roles. Existing narrator,
individual and category voice assignments take priority. This sends the book's
text and available avatar names to that provider and uses its API allowance.
Planning results are cached per text block; a saved manual `music_plan` in
`book.json` bypasses API initialization entirely. A fully silent scene is valid.

The default is a very quiet **-41 LUFS** background, with fades, quiet gaps and
gentle ducking beneath speech. Prompts request soft nonmelodic ambience without
vocals, a beat, piano or an orchestral foreground. Generation is limited to
45-second chunks with smooth joins. Music boundaries use the actual final
speech sample positions after loudness processing, pauses and edge trimming,
including the heading offset; estimated reading speed is not used.

Studio history and MP3/WAV exports point to the mix. Its metadata retains
`dry_mp3`, `dry_wav` and `dry_metadata`. Books retain `chapter-NNNN-dry.wav`,
its `.timeline.json`, and original cached voice clips; the normal chapter and
whole-book exports include music. The music choice and plan live in `book.json`.
Changing only the checkbox rebuilds the final mix without invalidating speech
checkpoints. Book music has its own stage progress bar alongside saved fragment
progress. Turning it off uses the retained voices to export speech again.

## Optional contextual sound effects

Open a book's **Звуки** tab and select **Генерировать звуковые эффекты**. This
independent, per-book choice is off by default; music may remain disabled.
Effects use the same Stable Audio 3 Medium and text encoder already installed
for music. If absent, the server prepares them automatically with download
progress; there is no second copy of the model for effects.

Analysis marks a source sound cue as `kind="sound"` and describes its source
from the scene. For example, «Скрип-скрип.» beside a passing cart should describe
cart-wheel creaking rather than ask the generator to pronounce those syllables.
The program generates the effect, caches it, and inserts its audio at that cue's
position. Surrounding narration remains unchanged. Effects have a separate
progress stage; they are generated sequentially with speech and music on the
same server. Only analyzed sound cues are eligible; ordinary narration and
character dialogue are not converted into effects.

An uploaded **manual file always wins**. Each cue also retains explicit
**Читать автором** and **Пропустить** choices. **Автоматически (ИИ / автор)**
uses AI when effect generation is enabled, otherwise narrator reading. Cached
AI audio can be previewed in the table and remains separate from a manually
selected file. Changing the checkbox retains unaffected speech checkpoints and
does not replace a saved voice take with effect audio. The existing cache works
per segment: a changed segment containing both speech and effects may need its
own voice parts rendered again; unrelated speech-only segments are reused.
A saved checked option can be cleared in local mode without reconnecting to SSH.

## Speech, emotions and progress

Choose an avatar with a clean 3–30 second reference and an accurate transcript.
When saving an avatar without a transcript, the server recognizes the reference
with Qwen3-ASR; local Whisper is not loaded in server mode. ASR can evict cached
speech weights, so the next first synthesis may load the model again.

Inline cues are passed through, for example:

```text
[happy] Получилось! [angry] Кто выключил свет?
[whispering] Кажется, здесь кто-то есть.
```

Book analysis can add optional `performance` metadata (`none`, `laughs`, or
`chuckles`) to a character's dialogue when the source explicitly confirms
laughter. The original `text`, punctuation, narrator clauses and markup remain
unchanged. For example, a confirmed part
`{"text":"— Ха! Ты угадал.","speaker":"Рик","performance":"laughs"}`
produces the separate Drama 3 input `[laughs heartily] Ты угадал.`. The point sound requests
audible laughter instead of reading the laugh syllables. Listen to verify the
result and voice similarity; text recognition alone cannot verify delivery.

The production renderer keeps a verbal scaffold with the action cue: tag-only
generation can invent speech and is not submitted automatically. A directly
adjacent plain continuation by the same actor can provide that scaffold; an
author or different-speaker boundary is never crossed. Without suitable spoken
words, the original interjection is retained. Metadata requests delivery rather
than guaranteeing audible laughter in every model output.

The analyzer must not infer laughter from a smile, a smirk, happiness, a rhetorical
«Ха!», a thoughtful «Хм», or a mention of the word «ха-ха». Narrator and non-content
parts cannot carry the action; «Рик рассмеялся» remains spoken narration. Ambiguous
«Ха?» and «Хм» are protected even if incorrectly directed. Adjacent parts retain
separate performance boundaries, and an author insertion does not repeat laughter
on the following dialogue. Previously saved books without this field keep their
existing delivery. The feature is applied only to Drama 3; local backends retain
their original text handling. Normal book analysis creates the metadata without
manual editing; the JSON example explains its saved representation.

The engine uses temperature 1.0, top_p 0.9 and top_k 0. It keeps natural pauses.
Studio WAV recordings preserve the native sample rate (44.1 kHz); MP3 is 192 kbps.
Book clips are resampled to 24 kHz mono for the existing chapter assembly and
loudness pipeline. The generation metadata records the original sample rate.
Clips reaching the generation cap are marked for review; there is no automatic
claim of transcript accuracy or automatic re-generation.

During synthesis, the UI shows the active stage and actual generated frame
count. The maximum frame count is a safety cap, **not an estimate of total work**,
so generation uses an activity indicator instead of a misleading percentage.
Audiobooks also show overall fragment progress and save completed fragments.
The existing book Pause/Stop behavior at fragment/chapter boundaries is retained.
Studio's **Отменить озвучку** cancels only the submitted server job using the
atomic `/api/jobs/{id}/cancel` endpoint; it never interrupts unrelated jobs or
clears the server queue. Force-stop and app-close wait asynchronously for an
acknowledgment before killing the local worker or SSH tunnel. Durable local job
receipts also cover a lost submission response and can reconnect to the same
server port. If cancellation cannot be confirmed, the worker/tunnel stays alive
and the app reports the job ID and a retryable error. New jobs and server changes
stay blocked until **Повторить отмену** receives acknowledgment. This also covers
an ordinary transport error that leaves a durable receipt, even after switching
to local speech mode; a restart or close must resolve the owned remote job first.

## Client installation without local GPU models

From the extracted source folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -RemoteOnly
```

This installs `requirements-client.txt`, without local Torch/CUDA, Whisper or
speech weights. The Windows installer has the equivalent **SSH server client /
Клиент SSH-сервера** checkbox. A new client starts with unconfigured remote
preferences, opens the studio without loading a local model, and leaves generation
disabled while **Озвучка / SSH-сервер** remains available. Existing preferences are
never overwritten by setup. Then run `start.cmd` and configure SSH as above. For book analysis
on such a client, select an API provider under **Модель разметки / API**. Studio
numbers are read natively by Drama 3 and do not invoke a local language model.
The standard Windows installer continues to install the full local configuration.

## Connection and data

OpenSSH Client must be installed on Windows. Host keys are pinned in
`data/ssh/known_hosts`, with the user's standard known_hosts also consulted.
The first connection accepts a previously unknown host; a changed host key is
rejected and must be checked by the user. SSH keys stay on the client. Only the
connection string, key **path**, and music preference are saved locally in `data/tts-settings.json`.
The SSH forward binds to 127.0.0.1 on both sides; no public ComfyUI port is needed.

Speech text and reference audio are sent to the configured server. Uploaded
references and generated ComfyUI outputs remain in its input/output directories;
manage their retention with the server owner. Local book and avatar data remain
under `data`. Server credentials are excluded from releases and Git.

Licenses: [Fish Audio Drama 3](https://huggingface.co/fishaudio/drama-3),
[ComfyUI-Drama3 notices](https://github.com/PedroMarinhoDev/ComfyUI-Drama3).
Drama 3 uses the Fish Audio Research License; consult its terms for commercial use.

## Validation

```powershell
python -m unittest discover -v
```

Tests cover SSH command/URI validation, host-key policy, the JSON transport,
Range resume and full-response restart, hashes, cache identity, scoped job
cancellation, WebSocket fallback, audio download and Qt progress/dialog states.
They do not download model weights. A live generation needs the above GPU server.
