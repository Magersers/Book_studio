# Installation and model downloads

The Windows setup EXE is a **bootstrap installer**, not a bundled offline model. It embeds the same clean source ZIP published in the release and runs `setup.ps1` in the chosen installation folder (default `%LOCALAPPDATA%\BookStudio`). Existing data is not included in or deleted by the package. Close the application before installing over an existing copy.

Setup downloads Python 3.12.10 from python.org when its local environment is absent, checks the installer's Authenticode signature, and installs it privately into `.python`. Python dependencies live in `.venv`. It installs PyTorch 2.6.0 / torchaudio 2.6.0 CUDA 12.4, then `requirements.txt` with the setuptools build constraint. The exact package list is in the repository. Network access to python.org, PyPI, download.pytorch.org, GitHub and model hosting is needed.

`download_upgrade.py` installs:

| Resource | Source |
| --- | --- |
| Higgs 4B Q8 GGUF | `audio-cpp/audio.cpp-gguf`, `Higgs-Audio-v3-TTS-4B-GGUF/higgs-audio-v3-tts-4b-q8_0.gguf` |
| Qwen3.5 9B Q4_K_M | `unsloth/Qwen3.5-9B-GGUF`, `Qwen3.5-9B-Q4_K_M.gguf` |
| Speech CUDA runtime | `0xShug0/audio.cpp`, release `v0.9.0` |
| Analysis CUDA runtime | `ggml-org/llama.cpp`, release `b11146` |

Model downloads use resumable parts and file hash verification. Hash metadata is resolved from the hosting repository at install time. ModelScope can serve as a mirror when the file hash matches. `download_ocr.py` downloads Russian and English OCR data. Whisper weights are fetched on first use if transcription needs them. Downloaded files keep their upstream licenses; review those before commercial use.

No API key is required for local analysis. For cloud analysis, open the API dialog and enter a key from your provider. Switching the endpoint requires a key for that endpoint; keys are not silently reused across servers. The currently saved API profile is retained when switching back to local mode. There is one saved API profile, not a key vault for multiple providers.

Custom providers must expose `/models` for discovery and support streaming `/chat/completions` with `response_format: {"type":"json_object"}`. Discovery can be skipped by typing a model ID. Models with smaller context/output limits may require smaller workloads; availability in `/models` alone does not certify schema compatibility. DeepSeek-specific `thinking` options are omitted for other providers.

Troubleshooting: rerun setup after a download/network failure; check `logs` for runtime errors; verify NVIDIA driver compatibility and available VRAM. Do not run two GPU-heavy tasks simultaneously. Copy `data` and `outputs` to back up books and avatars. DPAPI-encrypted API keys cannot be moved to another Windows account; enter them again there.

Upstream references: [Python 3.12.10](https://www.python.org/downloads/release/python-31210/), [DeepSeek API](https://api-docs.deepseek.com/), [OpenRouter API](https://openrouter.ai/docs/api_reference/overview).
