# RouterAI Drama 3

## Configure speech

1. Obtain a RouterAI API key from your account.
2. Open **Озвучка / RouterAI** and enter the key.
3. The endpoint is `https://routerai.ru/api/v1`; the model is `fish-audio/drama-3`.
4. Optionally press **Проверить API-ключ**, then save.

The check performs read-only `GET /models`. It does not generate speech, check a clone's sound, or reserve a price. Current pricing and account limits are shown by [RouterAI](https://routerai.ru/models/fish-audio/drama-3).

Saved keys are encrypted with Windows DPAPI. An advanced installation can instead supply `ROUTERAI_API_KEY` in the process environment for the standard RouterAI endpoint. Keys are excluded from speech cache identities and audio reports.

## Voice references and emotions

Select a voice avatar in the studio or assign avatars to the narrator and characters of a book. Each synthesis request includes the selected recording inline as a Fish Audio reference, together with its exact transcript. The app does not publish the sample to a public voice library.

New references must contain 3–30 seconds of audible speech. Enter the words spoken in the selected interval exactly; existing avatar transcripts and bundled references are retained. Automatic reference transcription is not part of this API workflow.

The text carries Drama 3 emotional/performance directions. The app forwards native Fish Audio attributes inside RouterAI's provider options:

```json
{
  "model": "fish-audio/drama-3",
  "input": "[warm and delighted] We made it!",
  "voice": "alloy",
  "response_format": "mp3",
  "provider": {
    "options": {
      "fish-audio": {
        "references": [
          {"audio": "BASE64_OF_SELECTED_WAV", "text": "Exact words from the recording."}
        ],
        "reference_id": null,
        "temperature": 1.0,
        "top_p": 0.9
      }
    }
  }
}
```

The generic envelope's voice alias is cleared at the native provider layer by `reference_id: null`; the inline selected avatar is the reference. The program controls the sample, text, seed and output format for each fragment.

## Advanced Fish Audio parameters

In **Дополнительные параметры Fish Audio · JSON**, enter an object containing only the additional native options you want to change, for example:

```json
{"temperature": 0.9, "top_p": 0.9}
```

This object becomes `provider.options["fish-audio"]`, merged with the program's defaults and selected voice. Reserved fields such as `references`, `reference_id`, `voice`, `model`, `seed`, format and credentials are managed by the app and rejected in this field. Provider acceptance of additional options depends on its API.

Changing speech parameters changes the synthesis cache identity. Music settings and API credentials do not change speech cache identities.

## Progress, cancellation and billing

The app displays request, synthesis and audio-download stages. While the provider does not expose a synthesis percentage, progress is indeterminate.

A paid speech POST is submitted once. On failure, completed fragments remain saved and the next attempt is explicit. Closing a request cannot prove the provider stopped processing it, so an interrupted request can still be charged.

Local music and sound effects have their own progress and cancellation. They are generated on the PC and mixed with the saved speech. Their model setup is described in [INSTALL.md](INSTALL.md).

The full application, local model installation, builds and test suite were not run. One separately authorized API request with the narrator reference returned audio in 5.05 seconds for a 174-character directed script. This checks that request, not the complete desktop workflow or 8 GB GPU compatibility. No API key or private voice recording is included in this change.

References: [RouterAI Drama 3](https://routerai.ru/models/fish-audio/drama-3), [RouterAI TTS options](https://routerai.ru/docs/guides/overview/multimodal/text-to-speech), [Fish Audio TTS API](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech).
