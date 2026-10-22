# RouterAI Drama 3

## Configure speech

1. Obtain a RouterAI API key from your account.
2. Open **Озвучка / RouterAI** and enter the key.
3. The endpoint is `https://routerai.ru/api/v1`; the model is `fish-audio/drama-3`.
4. For audiobooks, choose **Параллельных запросов** (**Concurrent requests**): **3** by default, from **1 to 8**. Reduce it if the provider limits requests; 1 runs sequentially.
5. Optionally press **Проверить API-ключ**, then save.

The check performs read-only `GET /models`. It does not generate speech, check a clone's sound, or reserve a price. Current pricing and account limits are shown by [RouterAI](https://routerai.ru/models/fish-audio/drama-3).

Saved keys are encrypted with Windows DPAPI. An advanced installation can instead supply `ROUTERAI_API_KEY` in the process environment for the standard RouterAI endpoint. Keys are excluded from speech cache identities and audio reports.

## Fish Audio voices and emotions

Select a Fish Audio voice avatar in the studio or assign avatars to the narrator and characters of a book. Each request sends the selected Fish Audio model ID in the top-level `voice` field. The provider is fixed to `fish-audio`.

To use a custom voice, create it on [Fish Audio](https://fish.audio/) first, copy the 32-character ID from its share link (`https://fish.audio/m/<ID>`), and enter it in the avatar's **Fish Audio ID** field. Creating or publishing a clone on Fish Audio is a separate operation; this app does not upload a recording or create a voice automatically. Access to private models depends on the provider account; an ID alone does not grant access.

Local recordings, existing transcripts and book assignments are retained during an update. A local avatar without a Fish Audio ID must be linked to a model before synthesis. It fails with an actionable message before a paid request instead of silently speaking with a default voice. A catalog voice needs no local WAV or reference transcript.

Tests with this RouterAI endpoint returned speech for known Fish model IDs. Inline `references` were accepted even when invalid and did not provide confirmed cloning. The application therefore uses voice IDs rather than inline MP3/WAV references.

The text carries Drama 3 emotional/performance directions. For example:

```json
{
  "model": "fish-audio/drama-3",
  "input": "[warm and delighted] We made it!",
  "voice": "7312c38557eb4fb384e3874e8e9cea67",
  "response_format": "mp3",
  "provider": {
    "only": ["fish-audio"]
  }
}
```

The program preserves emotional tags and voice assignments. It requests MP3, then validates the returned audio and converts it to the project's mono WAV sample rate. Different voices have separate cache signatures; audio cached by the earlier inline-reference backend is invalidated.

## Advanced Fish Audio parameters

In **Дополнительные параметры Fish Audio · JSON**, enter an object containing only the additional native options you want to change, for example:

```json
{"temperature": 0.9, "top_p": 0.9}
```

This object becomes `provider.options["fish-audio"]`, alongside program-managed seed and MP3 output options. Reserved fields such as `references`, `reference_id`, `voice`, `model`, `seed`, format and credentials are rejected in this field. RouterAI may ignore unsupported options; their presence in a successful request does not confirm they affected the sound. In particular, changing a seed does not guarantee deterministic synthesis.

Changing speech parameters changes the synthesis cache identity. Music settings, the number of concurrent requests and API credentials do not change speech cache identities.

## Progress, cancellation and billing

The app displays request, synthesis and audio-download stages. While the provider does not expose a synthesis percentage, progress is indeterminate.

Audiobook speech submits at most the selected number of segments at once, with an independent API client and HTTP session for each worker. Finished fragments are saved individually, and the final chapter follows the original text order regardless of which request finishes first. Assigned voices and performance tags are preserved. This setting affects audiobook speech; local music and sound effects continue to use one shared local runtime.

A paid speech POST is submitted once. On failure, new submissions stop while successful requests already in flight are saved. Completed fragments remain available, and the next attempt is explicit. Pausing waits for submitted work to be saved; stopping API speech keeps its completed checkpoints. Closing a request cannot prove the provider stopped processing it, so an interrupted request can still be charged.

Local music and sound effects have their own progress and cancellation. They are generated on the PC and mixed with the saved speech. Their model setup is described in [INSTALL.md](INSTALL.md).

`test_routerai_engine.py` checks exact voice/provider forwarding without recordings, valid audio decoding, studio synthesis without a transcript, voice-specific cache invalidation, preservation of existing audio on errors, and one-attempt behavior on payment/network failures. `test_book_parallel.py` covers bounded audiobook workers, ordering and checkpoints; `test_tts_concurrency_settings.py` covers the saved 1–8 preference and its interface. HTTP responses are mocked and audio conversion uses ffmpeg. Live API availability and the accessibility of each catalog voice remain provider-dependent. No API key or personal voice recording is included in the source change.

References: [RouterAI Drama 3](https://routerai.ru/models/fish-audio/drama-3), [RouterAI TTS options](https://routerai.ru/docs/guides/overview/multimodal/text-to-speech), [Fish Audio TTS API](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech).
