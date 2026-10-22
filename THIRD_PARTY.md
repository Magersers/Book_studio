# Third-party components

Book Studio downloads model weights and native runtimes separately. Their licenses and usage restrictions are independent of this application's source. This file is a component index, not a replacement for upstream license notices. No third-party model weights are bundled in the release.

- [audio.cpp](https://github.com/0xShug0/audio.cpp) and [GGUF model files](https://huggingface.co/audio-cpp/audio.cpp-gguf): native speech runtime and Higgs Audio v3 TTS 4B conversion. Consult the runtime repository and model card for the original model terms.
- [llama.cpp](https://github.com/ggml-org/llama.cpp): local analysis runtime.
- [Qwen3.5 9B GGUF](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF): analysis weights and upstream model attribution.
- [Whisper](https://github.com/openai/whisper): voice-reference transcription.
- [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html): desktop UI; Qt's applicable open-source or commercial terms apply.
- [PyTorch](https://pytorch.org/), [Transformers](https://github.com/huggingface/transformers), [Hugging Face Hub](https://github.com/huggingface/huggingface_hub): inference and model downloads.
- [PyMuPDF](https://pymupdf.readthedocs.io/en/latest/about.html): PDF extraction, subject to its AGPL/commercial licensing options. Review licensing before redistributing or commercializing a derivative.
- [FFmpeg / imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg): audio conversion; actual bundled FFmpeg build terms apply.
- [Tesseract language data](https://github.com/tesseract-ocr/tessdata_fast), python-docx, Beautiful Soup, striprtf and defusedxml: document import/OCR support.
- Natasha, pymorphy3 and num2words: Russian text normalization.
- Legacy optional Qwen-TTS dependencies are retained for compatibility with older local configurations. The default setup selects Higgs.

See `requirements.txt` for Python package versions and installed package metadata for full notices. Dependencies are installed from their upstream distributions rather than embedded into the small setup executable. An application source license has not yet been selected by the repository owner.

Optional SSH speech runtime: [Fish Audio Drama 3](https://huggingface.co/fishaudio/drama-3)
uses the Fish Audio Research License. The original FP8 expert weights and codec
are distributed in ComfyUI format by [PedroMarinhoDev](https://huggingface.co/PedroMarinhoDev/Drama-3-ComfyUI).
[ComfyUI-Drama3](https://github.com/PedroMarinhoDev/ComfyUI-Drama3) is GPL-3.0 with
additional Apache-2.0 and Fish Audio notices for bundled components;
[ComfyUI](https://github.com/Comfy-Org/ComfyUI) is GPL-3.0. Qwen3-ASR is Apache-2.0.
The optional [Stable Audio 3 Medium](https://huggingface.co/stabilityai/stable-audio-3-medium)
model and T5Gemma encoder use the official [Comfy-Org conversion](https://huggingface.co/Comfy-Org/stable-audio-3).
Retain and consult the upstream model cards and license notices for their terms.
These components and models are downloaded to the
user's server separately. See [SSH setup](docs/SSH-SERVER.md) for pinned revisions.
The desktop uses websocket-client (Apache-2.0) for live generation events.

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
