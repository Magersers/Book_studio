# Voice catalog and legacy recordings

## Russian Fish Audio catalog

`assets/voices/fish-audio-ru.json` contains a snapshot of public voice metadata
returned by Fish Audio's Russian language filter. It records names, descriptions,
tags, author attribution, voice IDs and links. Recordings and model weights are
not downloaded into this catalog.

Setup and the first desktop launch add missing entries under **Fish Audio · RU**.
Folders use the declared gender and descriptions/tags: narrators, characters,
children, older voices, young voices and other voices. Missing gender metadata
goes under **Пол не указан**. Search includes names, folders, authors,
descriptions and tags. Preview plays the public sample URL when available;
otherwise it opens the voice's Fish Audio page.

Synthesis sends the selected 32-character Fish Audio ID through RouterAI Drama 3.
No local reference WAV or transcript is required. For a custom voice, create it
on Fish Audio first and enter its ID in an avatar. See [RouterAI setup](ROUTERAI.md).

The snapshot is not a live subscription: voices added, removed or restricted on
Fish Audio after collection may differ. Popularity is the recorded collection
value. Imported IDs are stable (`fish` followed by the Fish model ID), so an
update retains edited and archived avatars, folder moves and book assignments.
Public listing does not itself grant rights to use a voice commercially;
the creator's and service's terms apply.

## Legacy local reference pack

The release includes short reference WAVs and an attribution manifest under
`assets/voices`. These are reference recordings, not speech-model weights.
The manifest records each voice's display name, exact reference transcript,
description, original source and SHA-256 checksum.

Setup and the first desktop launch install missing voices into the library's
**Студийные · RU** folder. The same check runs after an application update, so
newly added voices become available in an existing installation too. No server,
GPU or transcription download is needed to register them. These local-only
avatars need a Fish Audio ID before they can synthesize through RouterAI.
RouterAI does not provide confirmed inline MP3/WAV cloning through this endpoint.
The original recordings and transcripts remain available for the user's own
voice preparation workflow.

An existing avatar with the same stable ID is never replaced or re-enabled.
Edited and archived avatars, folder choices and book voice assignments remain
the user's choices. New voices are available for selection; existing books are
not silently recast. Moving or renaming a bundled avatar works like any other
library avatar.

### Included Russian reference recordings

The five references are recordings of real speakers, resampled to 24 kHz mono
PCM16. No generated voice is used as a bundled reference. Character names are
casting labels for the test; they do not identify the recording's performer.

| Library voice / test role | Recording source | Terms recorded upstream |
| --- | --- | --- |
| Рассказчик · студийный баритон | [RESD](https://huggingface.co/datasets/Aniemore/resd), dialogue 18 | Dataset card: MIT |
| Элбридж · Дмитрий | [Dialogs](https://huggingface.co/datasets/langswap/dialogs-ru-emotional-conversations), Dima, a professional theatre actor | OpenRAIL |
| Рик · студийный мужской | RESD, dialogue 27 | Dataset card: MIT |
| Старуха · Людмила | [Sakrament IT / Людмила Русакевич](https://github.com/sakrament/st_ru_rusakevich) | **CC-BY-NC-SA-4.0** |
| Архиепископ · студийный мужской | RESD, dialogue 50 | Dataset card: MIT |

RESD dialogue numbers are not actor identifiers. The published metadata does not
establish the three performers' names, ages or whether they are different people.
The role assignments are provisional listening choices.

**The Людмила reference has a noncommercial restriction.** Its source is copyright
2016 Sakrament IT Ltd., distributed under Creative Commons
Attribution-NonCommercial-ShareAlike 4.0 International. The resampled recording
retains those terms: preserve attribution, identify the resampling, and follow
the license's noncommercial and share-alike conditions. The other voices' terms
do not remove this restriction. Commercial rights for this recording are not
granted by its inclusion in the application.

Dialogs' supplied OpenRAIL license includes use restrictions and redistribution
conditions. The RESD card declares MIT; its upstream release has no separate
license text. The original source paths, revisions or recording URLs, original
and packaged SHA-256 values, transcripts and processing notes are retained per
voice in `assets/voices/manifest.json`.

Source notices and the supplied license texts ship under
`assets/voices/licenses/`. Speech-model terms apply separately from the reference
recording terms.

### Legacy manifest format

`assets/voices/manifest.json` uses version 1:

```json
{
  "version": 1,
  "pack_id": "studioru",
  "voices": [
    {
      "id": "studionarratorru",
      "name": "Студийный рассказчик",
      "file": "assets/voices/studionarratorru.wav",
      "sha256": "SHA256_OF_THE_PACKAGED_WAV",
      "transcript": "Exact transcript of the reference recording.",
      "duration": 10.0,
      "description": "Calm adult narrator.",
      "gender": "male",
      "source": {
        "url": "https://example.org/original-voice-source",
        "title": "Reference source and generation provenance",
        "license": "Source and model terms applicable to this reference."
      }
    }
  ]
}
```

The importer accepts only the matching `assets/voices/<id>.wav` path, including
after symlink resolution. Samples must be 3–30 seconds of uncompressed 24 kHz
mono PCM WAV. All manifest entries and checksums are validated before writing
to the library. IDs are stable ASCII letters and digits, matching the avatar
store. Add the manifest and every WAV explicitly to `distribution.json` so they
ship in both the source ZIP and the embedded Windows installer.
