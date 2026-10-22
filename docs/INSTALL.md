# Installation

[English overview](../README.md) · [Русский](../README.ru.md) · [RouterAI setup](ROUTERAI.md)

## Base desktop application

Use Windows 10/11 x64 and a writable installation folder. Download this branch from GitHub with **Code → Download ZIP**, extract it, and run `setup.cmd`. Start the application with its desktop shortcut or `start.cmd`.

`setup.ps1` accepts `-NoShortcut` when a shortcut is not wanted:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1 -NoShortcut
```

The base setup:

- Downloads private Python 3.12.10 from python.org when needed, checks the Python Software Foundation Authenticode signature, and creates `.venv`.
- Installs the desktop/API dependencies from `requirements-client.txt`.
- Registers the bundled voice references with their supplied transcripts.
- Keeps package caches under the chosen installation's `.cache` directory.

Speech uses RouterAI Drama 3. Save the RouterAI key under **Озвучка / RouterAI**. Annotation defaults to DeepSeek API and has separate provider/key settings. Enter the exact transcript of a new avatar's selected reference interval. No speech or transcription weights are installed by base setup.

The current change is source-only: no new installer or release archive has been built. Close the application and back up `data` and `outputs` before replacing an existing installation's source files; then rerun setup. Existing preferences and downloaded local-audio weights are retained.

## Optional local music and effects

**Background music** and **Generate sound effects** are independent. Both use the same Stable Audio 3 Medium weights. Installation starts on first use or through **Подготовить музыку и звуки** in speech settings. Download and preparation stages have progress and cancellation controls.

The isolated runtime lives under `models/local-audio`; it does not start an HTTP service. It uses ComfyUI's Python inference libraries in a separate worker process, with PyTorch attention.

| Resource | Pinned source |
| --- | --- |
| Inference library | ComfyUI commit `355cd6b14c92c19ac3188fe528e47a3f21ef5178` |
| Medium weights | `Comfy-Org/stable-audio-3`, revision `75aad8836271cb5a5123fb58304fae5d3bb4b0f9`, `checkpoints/stable_audio_3_medium.safetensors` |
| Text encoder | Same revision, `text_encoders/t5gemma_b_b_ul2.safetensors` |
| CUDA Python packages | PyTorch 2.11.0, torchvision 0.26.0, torchaudio 2.11.0 from the official CUDA 12.8 wheel index |

The two model files total approximately **10.4 GB**. Allow additional disk space for the inference source, Python environment, package caches and generated audio. Weight sizes and SHA-256 hashes are pinned in `local_audio_runtime.py`; dependency constraints are in `requirements-audio.txt`. Interrupted weight downloads resume when the origin confirms byte ranges.

### An 8 GB GPU

The default audio path generates blocks of at most 15 seconds. Text encoding and VAE decoding use CPU memory; diffusion uses the GPU with offloading, a VRAM reserve and tiled audio decoding. A compatible NVIDIA driver is required for the CUDA option; a system CUDA Toolkit is not required.

This is a memory-conscious configuration, not a measured guarantee for every 8 GB card. System RAM is used for offloading. If CUDA is unavailable or the workload does not fit, select **CPU** under **Устройство для музыки и звуков**, save, and start generation again. CPU processing is slower.

The application, local audio installation and generation were not executed for this change, at the user's request.

## Keys, data and recovery

API keys saved through the UI use Windows DPAPI. They are bound to the current Windows account; enter them again after moving to another account or PC. Personal data is in `data` and generated outputs in `outputs`; keep both when upgrading.

The speech API check uses read-only model discovery and does not synthesize paid audio. It confirms key/model access, not a completed voice-cloning request. Speech POST requests are not retried automatically after a failure.

For local-audio installation failures, retry **Подготовить музыку и звуки**. Check `models/local-audio/install.log` and `generation.log` for details. Logs may contain prompts or book text; review them before sharing.

Older installations can retain their local annotation configuration. Select an API under **Модель разметки / API** if its previous local model is absent; current setup does not download local annotation weights.

Upstream: [RouterAI TTS](https://routerai.ru/docs/guides/overview/multimodal/text-to-speech), [Python 3.12.10](https://www.python.org/downloads/release/python-31210/), [PyTorch](https://pytorch.org/), [ComfyUI](https://github.com/Comfy-Org/ComfyUI), [Stable Audio 3 conversion](https://huggingface.co/Comfy-Org/stable-audio-3).
