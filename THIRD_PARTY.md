# Third-party components

Model, API, runtime and reference-recording terms apply independently of the application source. This index does not replace upstream license notices. The source package includes the attributed voice references described below; model weights are downloaded separately when local audio is requested.

## Active speech and local audio

- [RouterAI](https://routerai.ru/models/fish-audio/drama-3) provides the hosted [Fish Audio Drama 3](https://docs.fish.audio/features/text-to-speech/drama-3) speech API. Provider terms and API pricing apply. The application sends the selected voice sample and text for synthesis; local Drama 3 weights are not distributed by this workflow.
- [Stable Audio 3 Medium](https://huggingface.co/stabilityai/stable-audio-3-medium) and the T5Gemma text encoder are downloaded through the official [Comfy-Org conversion](https://huggingface.co/Comfy-Org/stable-audio-3). Consult and retain the upstream model cards and license notices for their terms.
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI), GPL-3.0, supplies Python inference libraries for optional local music and effects. The isolated worker uses these libraries without starting an HTTP service. [INSTALL.md](docs/INSTALL.md) records the pinned source/model revisions.
- [PyTorch](https://pytorch.org/), [Transformers](https://github.com/huggingface/transformers), [safetensors](https://github.com/huggingface/safetensors) and [Hugging Face Hub](https://github.com/huggingface/huggingface_hub) supply inference and model-loading dependencies. Installed distributions retain their upstream notices.

## Desktop and document processing

- [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html): desktop UI; Qt's applicable open-source or commercial terms apply.
- [PyMuPDF](https://pymupdf.readthedocs.io/en/latest/about.html): PDF extraction, subject to its AGPL/commercial licensing options. Review licensing before redistributing or commercializing a derivative.
- [FFmpeg / imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg): audio conversion; the actual bundled FFmpeg build terms apply.
- [Tesseract language data](https://github.com/tesseract-ocr/tessdata_fast), python-docx, Beautiful Soup, striprtf and defusedxml: document import/OCR support.
- Natasha, pymorphy3 and num2words: Russian text normalization.
- [Requests](https://requests.readthedocs.io/): HTTPS API requests and downloads.
- Existing local annotation compatibility uses [llama.cpp](https://github.com/ggml-org/llama.cpp) and [Qwen3.5 9B GGUF](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF). Their terms remain relevant to installations retaining those components; current base setup does not download these weights.

See `requirements-client.txt`, `requirements-audio.txt` and installed package metadata for dependency versions and full notices. Dependencies are installed from upstream distributions. An application source license has not yet been selected by the repository owner.

## Bundled reference recordings

Bundled reference voice recordings have their individual sources and applicable
terms recorded in `assets/voices/manifest.json`. See the [voice-pack guide](docs/VOICE-PACK.md)
for installation and provenance handling. These short recordings are separate
from model weights; their presence does not grant rights to the upstream models.

- [RESD / Russian Emotional Speech Dialogs](https://huggingface.co/datasets/Aniemore/resd),
  Artem Amentes, Ilya Lubenets and Nikita Davidchuk (2022): three real human
  studio-recorded reference clips. The upstream dataset card declares MIT; no
  separate upstream LICENSE file is published. See
  `assets/voices/licenses/RESD-NOTICE.txt` and the manifest for exact source rows.
- [Dialogs](https://huggingface.co/datasets/langswap/dialogs-ru-emotional-conversations),
  Ilya Shigabeev and Ilya Latyshev (Langswap): the Dima reference is distributed
  with `assets/voices/licenses/DIALOGS-OpenRAIL.md`. The supplied OpenRAIL license
  has use restrictions and redistribution conditions.
- [Sakrament IT / st_ru_rusakevich](https://github.com/sakrament/st_ru_rusakevich),
  copyright 2016 Sakrament IT Ltd., speaker Людмила Русакевич: one real spoken
  reference, resampled from 48 kHz to 24 kHz mono PCM16. **CC-BY-NC-SA-4.0** applies
  to this reference, including its noncommercial restriction, attribution and
  share-alike conditions. The full supplied license is
  `assets/voices/licenses/RUSAKEVICH-CC-BY-NC-SA-4.0.txt`. Inclusion in the package
  does not grant commercial rights for this recording.
