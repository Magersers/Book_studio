"""Private stdin/stdout inference worker. It never creates a network listener."""
import argparse
import contextlib
import json
import math
from pathlib import Path
import sys


def emit(kind, **fields):
    sys.__stdout__.write(json.dumps(dict(type=kind, **fields), ensure_ascii=True) + '\n')
    sys.__stdout__.flush()


def progress(value, message):
    emit('progress', value=value, message=message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--device', choices=('auto', 'cuda', 'cpu'), default='auto')
    parser.add_argument('--offload', action='store_true')
    config = parser.parse_args()
    root = Path(config.runtime).resolve()
    sys.path.insert(0, str(root / 'inference'))
    import comfy.options
    comfy.options.enable_args_parsing()
    # Library-only import: main.py, PromptServer and application node setup are
    # never called. The text encoder remains on the CPU on an 8 GB card.
    sys.argv = ['local-audio', '--use-pytorch-cross-attention', '--disable-xformers',
                '--disable-dynamic-vram', '--disable-comfy-compiler', '--disable-pinned-memory',
                '--disable-async-offload', '--reserve-vram', '1']
    if config.device != 'cpu': sys.argv += ['--fp16-unet']
    if config.device == 'cpu':
        sys.argv += ['--cpu']
    elif config.offload:
        sys.argv += ['--lowvram', '--disable-smart-memory', '--cpu-vae']
    import torch
    if config.device != 'cpu' and not torch.cuda.is_available():
        raise RuntimeError('Для Stable Audio 3 Medium нужна NVIDIA CUDA. Обновите драйвер или выберите CPU (медленно).')
    import comfy.model_management as memory
    import comfy.sample
    import comfy.sd
    import soundfile as sf
    progress(None, 'Загружаем локальную Stable Audio 3 Medium…')
    model, _, vae, _ = comfy.sd.load_checkpoint_guess_config(
        str(root / 'models/checkpoints/stable_audio_3_medium.safetensors'),
        output_vae=True, output_clip=False, disable_dynamic=True)
    clip = comfy.sd.load_clip(
        [str(root / 'models/text_encoders/t5gemma_b_b_ul2.safetensors')],
        clip_type=comfy.sd.CLIPType.STABLE_AUDIO,
        model_options=dict(load_device=torch.device('cpu'), offload_device=torch.device('cpu')),
        disable_dynamic=True)
    for line in sys.stdin:
        request = json.loads(line)
        seconds = float(request['seconds'])
        if not 1 <= seconds <= 15.01: raise ValueError('Audio duration outside local limit')
        prompt, seed = request['prompt'], int(request['seed']) % (2**64)
        target = Path(request['output']).resolve()
        if target.parent != root or target.suffix != '.wav': raise ValueError('Invalid local output path')
        progress(None, 'Stable Audio 3: кодируем описание на CPU…')
        with torch.inference_mode():
            positive = clip.encode_from_tokens_scheduled(clip.tokenize(prompt))
            negative = clip.encode_from_tokens_scheduled(clip.tokenize(''))
            positive = [[x[0], dict(x[1], seconds_start=0., seconds_total=seconds)] for x in positive]
            negative = [[x[0], dict(x[1], seconds_start=0., seconds_total=seconds)] for x in negative]
            # Native SAME-Large: 256 channels, 4096 audio samples per latent.
            latent = torch.zeros((1, 256, max(2, math.ceil(seconds * 44100 / 4096))), device='cpu')
            latent = comfy.sample.fix_empty_latent_channels(model, latent, downscale_ratio_temporal=4096)
            noise = comfy.sample.prepare_noise(latent, seed)
            def callback(step, x0, x, total):
                progress((step + 1) / total, f'Stable Audio 3: шаг {step+1}/{total}')
            samples = comfy.sample.sample(model, noise, 8, 1., 'lcm', 'simple',
                positive, negative, latent, callback=callback, disable_pbar=True, seed=seed)
            del noise, latent, positive, negative
            memory.unload_all_models()
            memory.soft_empty_cache()
            progress(None, 'Stable Audio 3: восстанавливаем звук короткими блоками…')
            waveform = vae.decode_tiled(samples, tile_x=64, tile_y=64, overlap=8).movedim(-1, 1)
            scale = torch.std(waveform, dim=[1, 2], keepdim=True) * 5.
            waveform = waveform / scale.clamp_min(1.)
            audio = waveform[0].to(device='cpu', dtype=torch.float32).transpose(0, 1).numpy()
            rate = getattr(vae, 'audio_sample_rate_output', getattr(vae, 'audio_sample_rate', 44100))
            audio = audio[:round(seconds * rate)]
            import numpy as np
            if audio.ndim != 2 or audio.shape[1] != 2 or not len(audio) or not np.isfinite(audio).all():
                raise RuntimeError('Модель вернула некорректный звук.')
            partial = target.with_suffix('.partial.wav')
            sf.write(str(partial), audio, rate, subtype='FLOAT')
            partial.replace(target)
            del waveform, samples, audio
            memory.unload_all_models(); memory.soft_empty_cache()
        emit('complete', output=str(target), sample_rate=rate)


if __name__ == '__main__':
    try:
        with contextlib.redirect_stdout(sys.stderr):
            main()
    except Exception as exc:
        message = str(exc)
        if 'out of memory' in message.casefold():
            message = ('Не хватает видеопамяти. Закройте другие GPU-программы и включите выгрузку в RAM; '
                       'для 8 ГБ используются блоки до 15 секунд. Можно выбрать CPU, это медленнее.')
        emit('error', message=message)
        raise SystemExit(1)
