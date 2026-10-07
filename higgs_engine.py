"""Persistent native CUDA Higgs TTS 3 4B; one inference per utterance."""
import atexit,io,json,os,socket,subprocess,time,uuid
from pathlib import Path
import numpy as np
import soundfile as sf
import requests
import imageio_ffmpeg
from voice_reference import prepare_reference,transcribe
from audio_cleanup import clean_onset
from higgs_text import prepare as prepare_speech,frame_budget

ROOT=Path(__file__).resolve().parent
MODEL=ROOT/'models/Higgs-TTS-3-4B/higgs-audio-v3-tts-4b-q8_0.gguf'

class IncompleteSpeech(RuntimeError):pass

class Pipeline:
    supports_narrator_styles=True
    def __init__(self):
        self.process=None;self.log=None;self.http=requests.Session();self.http.trust_env=False
        atexit.register(self.close)
    def close(self):
        if self.process:
            if self.process.poll() is None:self.process.terminate()
            try:self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            self.process=None
        if self.log:self.log.close();self.log=None
    def load(self,progress=lambda *a:None):
        if self.process and self.process.poll() is None:return self
        exe=next((ROOT/'vendor/audio-cpp').rglob('audiocpp_server.exe'),None)
        if not exe or not MODEL.is_file():raise RuntimeError('Higgs TTS 3 не установлен. Запустите download_upgrade.py.')
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        self.url=f'http://127.0.0.1:{port}'
        folder=ROOT/'.cache'/('higgs-'+uuid.uuid4().hex);folder.mkdir(parents=True)
        settings=dict(host='127.0.0.1',port=port,backend='cuda',device=0,threads=6,lazy_load=False,
            max_loaded_models=1,idle_unload_ms=0,models=[dict(id='higgs',family='higgs_audio_tts',path=str(MODEL),task='tts',mode='offline',
            session_options={'higgs_audio_tts.reference_cache_slots':'4','higgs_audio_tts.attention':'flash'})])
        path=folder/'server.json';path.write_text(json.dumps(settings),encoding='utf-8')
        env=os.environ.copy();dlls=[exe.parent,*(ROOT/'vendor/llama-cpp').rglob('bin'),ROOT/'vendor/llama-cpp',ROOT/'.venv/Lib/site-packages/torch/lib']
        env['PATH']=os.pathsep.join(map(str,dlls))+os.pathsep+env.get('PATH','')
        (ROOT/'logs').mkdir(exist_ok=True);self.log=(ROOT/'logs/higgs-runtime.log').open('ab',buffering=0)
        progress(.35,'Загружаем Higgs TTS 3 · 4B Q8 · CUDA…')
        self.process=subprocess.Popen([str(exe),'--config',str(path),'--no-ui'],cwd=exe.parent,env=env,
            stdout=self.log,stderr=self.log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        start=time.monotonic()
        try:
            while True:
                if self.process.poll() is not None:raise RuntimeError('Не удалось запустить Higgs. Подробности: logs/higgs-runtime.log')
                try:
                    if self.http.get(self.url+'/health',timeout=1).ok:return self
                except requests.RequestException:pass
                if time.monotonic()-start>180:raise RuntimeError('Higgs не загрузился за отведённое время.')
                time.sleep(.2)
        except BaseException:self.close();raise
    def _synthesize_clip(self,reference,text,transcript,seed,target,narrator_style=None,recovery=False):
        if not text.strip() or len(text)>500:raise ValueError('Фрагмент должен содержать от 1 до 500 символов.')
        spoken_text=prepare_speech(text)
        if not any(c.isalnum() for c in spoken_text):raise ValueError('В фрагменте нет слов для озвучки.')
        self.load();start=time.perf_counter()
        narrator_anchor=None
        if narrator_style:
            from narrator_reference import select
            reference,transcript,narrator_anchor=select(reference,transcript)
        from audio_level import normalized_file
        reference=normalized_file(reference,'reference')
        model_input=spoken_text;temperature=.8
        if narrator_style:
            from narrator_profiles import controlled_input,PROFILES
            model_input=controlled_input(spoken_text,narrator_style);temperature=PROFILES[narrator_style]['temperature']
        if recovery:temperature=.5
        options=dict(model='higgs',input=model_input,voice_ref=str(Path(reference).resolve()),
            reference_text=transcript,seed=int(seed),max_tokens=frame_budget(spoken_text),temperature=temperature,top_k=30,top_p=.8)
        response=self.http.post(self.url+'/v1/audio/speech',json=options,timeout=(5,300))
        if not response.ok:
            from avatar_store import atomic_json
            atomic_json(Path(target).with_suffix('.error.json'),dict(text=text,request=options,error=response.text[:3000]))
            if 'max_tokens' in response.text and 'before EOC' in response.text:
                raise IncompleteSpeech('Higgs не выдал конец аудио для реплики «'+text[:100]+'». Готовые фрагменты сохранены. Автоматических повторов нет. Подробности запроса сохранены в отчёте .error.json рядом с аудио.')
            raise RuntimeError('Higgs не смог озвучить фрагмент. Подробности сохранены в отчёте рядом с аудио.')
        audio,sr=sf.read(io.BytesIO(response.content),dtype='float32')
        if sr!=24000 or audio.ndim!=1 or not len(audio) or not np.isfinite(audio).all() or np.max(np.abs(audio))<1e-5:
            raise RuntimeError('Higgs вернул некорректное аудио.')
        audio,noise=clean_onset(audio,sr);audio*=min(1.,.98/max(float(np.max(np.abs(audio))),1e-6))
        target=Path(target);target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_suffix('.partial.wav')
        sf.write(temp,audio,sr);temp.replace(target)
        target.with_suffix('.cleanup.json').write_text(json.dumps(dict(model='higgs-tts-3-4b-q8',mode='single_pass',seed=int(seed),noise=noise,text=text,spoken_text=spoken_text,max_tokens=options['max_tokens'],
            narrator_style=narrator_style,model_input=model_input,reference_avatar_source=str(reference),temperature=temperature,
            narrator_anchor=narrator_anchor,
            trimmed_ms=noise['trimmed_ms'],needs_review=False,generation_seconds=round(time.perf_counter()-start,3)),ensure_ascii=False),encoding='utf-8')
        return str(target)
    def synthesize_book_clip(self,reference,text,transcript,seed,target,narrator_style=None):
        try:return self._synthesize_clip(reference,text,transcript,seed,target,narrator_style)
        except IncompleteSpeech:
            # Exactly one recovery pass, never recursive. Only the failed text.
            from higgs_text import speech_chunks
            from avatar_store import atomic_json
            target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
            pieces=list(speech_chunks(prepare_speech(text),limit=100))
            audio=[];missing=[]
            for i,piece in enumerate(pieces):
                part=target.with_name(target.stem+f'-recovery-{i}.wav')
                try:
                    self._synthesize_clip(reference,piece,transcript,int(seed)+1009+i,part,narrator_style,recovery=True)
                    samples=sf.read(part,dtype='float32')[0]
                except IncompleteSpeech:
                    missing.append(piece);samples=np.zeros(6000,dtype='float32')
                if audio:audio.append(np.zeros(2400,dtype='float32'))
                audio.append(samples)
            temp=target.with_suffix('.partial.wav');sf.write(temp,np.concatenate(audio),24000);temp.replace(target)
            atomic_json(target.with_suffix('.cleanup.json'),dict(model='higgs-tts-3-4b-q8',mode='bounded_recovery',text=text,
                needs_review=bool(missing),missing_text=missing,trimmed_ms=0,seed=int(seed)))
            return str(target)

    def synthesize(self,reference,text,reference_text='',start=0,duration=15,seed=42,progress=lambda *a:None):
        if not text.strip() or len(text)>6000:raise ValueError('Введите текст до 6000 символов.')
        from higgs_text import speech_chunks
        segments=list(speech_chunks(text))
        if not segments:raise ValueError('В тексте нет слов для озвучки.')
        folder=ROOT/'outputs'/('higgs_'+uuid.uuid4().hex[:12]);folder.mkdir(parents=True)
        sample=prepare_reference(reference,folder,start,duration)
        transcript=reference_text.strip() or transcribe(sample)
        self.load(progress)
        waves=[];reports=[]
        for i,segment in enumerate(segments):
            progress(.25+.65*i/len(segments),f'Higgs TTS 3: фрагмент {i+1}/{len(segments)}…')
            path=Path(self.synthesize_book_clip(sample,segment,transcript,int(seed)+i,folder/f'segment-{i:04d}.wav'))
            from speech_joins import trim,gap
            if waves:waves.append(np.zeros(24*gap({'text':segments[i-1],'avatar':'same'},{'avatar':'same'}),dtype='float32'))
            from audio_level import normalized_file
            waves.append(trim(sf.read(normalized_file(path),dtype='float32')[0],24000));reports.append(json.loads(path.with_suffix('.cleanup.json').read_text(encoding='utf-8')))
        audio=np.concatenate(waves);wav=folder/'speech.wav';mp3=folder/'speech.mp3';metadata=folder/'generation.json'
        sf.write(wav,audio,24000)
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-y','-i',str(wav),'-codec:a','libmp3lame','-b:a','192k',str(mp3)],check=True,capture_output=True)
        metadata.write_text(json.dumps(dict(model='higgs-tts-3-4b-q8',text=text,reference_text=transcript,duration_seconds=len(audio)/24000,
            sample_rate=24000,seed=seed,onset_cleanup=reports,needs_review=any(r.get('needs_review') for r in reports),missing_text=[t for r in reports for t in r.get('missing_text',[])]),ensure_ascii=False,indent=2),encoding='utf-8')
        progress(1,'Готово');return str(mp3),str(wav),str(metadata),transcript
