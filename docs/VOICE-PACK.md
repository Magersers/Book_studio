# Bundled reference voices

The release includes short reference WAVs and an attribution manifest under
`assets/voices`. These are reference recordings, not speech-model weights.
The manifest records each voice's display name, exact reference transcript,
description, original source and SHA-256 checksum.

Setup and the first desktop launch install missing voices into the library's
**Студийные · RU** folder. The same check runs after an application update, so
newly added voices become available in an existing installation too. No server,
GPU or transcription download is needed to register them. Synthesis still uses
RouterAI Drama 3 with the selected reference recording and transcript.

An existing avatar with the same stable ID is never replaced or re-enabled.
Edited and archived avatars, folder choices and book voice assignments remain
the user's choices. New voices are available for selection; existing books are
not silently recast. Moving or renaming a bundled avatar works like any other
library avatar.

## Included Russian voices

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

## Manifest format

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
