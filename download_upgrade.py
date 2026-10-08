"""Pinned, resumable downloads for the native Higgs and Qwen 9B upgrade."""
import hashlib,json,zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT=Path(__file__).resolve().parent

class DownloadError(RuntimeError): pass


def get_json(url):
    import requests,time
    for attempt in range(4):
        try:
            with requests.get(url,timeout=(15,60)) as response:
                response.raise_for_status();return response.json()
        except (requests.RequestException,ValueError):
            if attempt==3:raise DownloadError('Cannot read download metadata. Check your connection and run setup again.') from None
            time.sleep(2*(attempt+1))


def fetch(url,target,sha,size):
    import requests,time,uuid
    urls=[url] if isinstance(url,str) else list(url)
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        with target.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()==sha:return target
    partial=target.with_suffix(target.suffix+'.part')
    marker=partial.with_suffix(partial.suffix+'.json')
    identity=dict(sha256=sha,size=size)
    # Legacy partial files are a contiguous prefix and remain usable. Changed
    # remote versions are quarantined rather than mixed into the same file.
    try:old=json.loads(marker.read_text()) if marker.exists() else identity
    except (ValueError,OSError):old=None
    if partial.exists() and (old!=identity or partial.stat().st_size>size):
        partial.rename(partial.with_name(partial.name+'.invalid-'+uuid.uuid4().hex[:8]))
    marker.write_text(json.dumps(identity),encoding='utf-8')
    offset=partial.stat().st_size if partial.exists() else 0;chunk=4*1024*1024
    print('Downloading',target.name,'(resuming at',offset,'bytes)',flush=True)
    def block(begin):
        end=min(size-1,begin+chunk-1)
        for attempt in range(4):
            for source in urls:
                try:
                    with requests.get(source,headers={'Range':f'bytes={begin}-{end}','Accept-Encoding':'identity'},stream=True,timeout=(15,90)) as response:
                        response.raise_for_status()
                        if response.status_code!=206 or response.headers.get('Content-Range')!=f'bytes {begin}-{end}/{size}':
                            raise ValueError('Server did not honor byte range')
                        data=bytearray()
                        for piece in response.iter_content(256*1024):
                            data.extend(piece)
                            if len(data)>end-begin+1:raise ValueError('Oversized response')
                        if len(data)!=end-begin+1:raise ValueError('Incomplete response')
                        return data
                except (requests.RequestException,ValueError):pass
            if attempt<3:
                print('Connection interrupted; retrying',target.name,attempt+1,'/ 3',flush=True)
                time.sleep(2*(attempt+1))
        raise DownloadError('Could not download '+target.name+'. Completed bytes are saved. Run setup again to resume; try another network if the host is blocked.')
    with partial.open('ab') as out,ThreadPoolExecutor(max_workers=4) as pool:
        while offset<size:
            for data in pool.map(block,range(offset,min(size,offset+4*chunk),chunk)):
                out.write(data);out.flush();offset+=len(data)
            print(target.name,round(offset/size*100),'%',flush=True)
    with partial.open('rb') as f:valid=hashlib.file_digest(f,'sha256').hexdigest()==sha
    if not valid:
        partial.rename(partial.with_name(partial.name+'.invalid-'+uuid.uuid4().hex[:8]))
        raise DownloadError('Checksum mismatch: '+target.name+'. The damaged download was set aside; run setup again for a clean download.')
    partial.replace(target);marker.unlink(missing_ok=True)
    print('Verified',target.name,flush=True);return target

def model(repo,file,dest):
    info=get_json('https://huggingface.co/api/models/'+repo+'?blobs=true')
    item=next(x for x in info['siblings'] if x['rfilename']==file)
    url=[f'https://huggingface.co/{repo}/resolve/{info["sha"]}/{file}']
    mirror='HereIsMark/audio.cpp-gguf' if repo=='audio-cpp/audio.cpp-gguf' else repo
    try:
        files=get_json(f'https://modelscope.cn/api/v1/models/{mirror}/repo/files?Revision=master&Recursive=true')['Data']['Files']
        same=next(x for x in files if x['Path']==file)
        if same['Sha256']==item['lfs']['sha256'] and same['Size']==item['size']:
            url.append(f'https://modelscope.cn/models/{mirror}/resolve/master/{file}')
    except (KeyError,StopIteration,DownloadError,TypeError):pass
    return fetch(url,ROOT/'models'/dest/Path(file).name,item['lfs']['sha256'],item['size'])

def runtime():
    info=get_json('https://api.github.com/repos/0xShug0/audio.cpp/releases/tags/v0.9.0')
    asset=next(x for x in info['assets'] if x['name']=='audio-v0.9.0-bin-windows-x64-cuda12.4.zip')
    archive=fetch(asset['browser_download_url'],ROOT/'.cache'/asset['name'],asset['digest'].split(':')[1],asset['size'])
    dest=ROOT/'vendor/audio-cpp';dest.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        if any(not (dest/x.filename).resolve().is_relative_to(dest.resolve()) for x in z.infolist()):raise ValueError('Unsafe archive path')
        z.extractall(dest)

def roles_runtime():
    if (ROOT/'vendor/llama-cpp/llama-server.exe').is_file():return
    info=get_json('https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b11146')
    dest=ROOT/'vendor/llama-cpp';dest.mkdir(parents=True,exist_ok=True)
    for name in ['llama-b11146-bin-win-cuda-12.4-x64.zip','cudart-llama-bin-win-cuda-12.4-x64.zip']:
        asset=next(x for x in info['assets'] if x['name']==name)
        archive=fetch(asset['browser_download_url'],ROOT/'.cache'/name,asset['digest'].split(':')[1],asset['size'])
        with zipfile.ZipFile(archive) as z:
            if any(not (dest/x.filename).resolve().is_relative_to(dest.resolve()) for x in z.infolist()):raise ValueError('Unsafe archive path')
            z.extractall(dest)

if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs=[pool.submit(runtime),pool.submit(roles_runtime),pool.submit(model,'audio-cpp/audio.cpp-gguf','Higgs-Audio-v3-TTS-4B-GGUF/higgs-audio-v3-tts-4b-q8_0.gguf','Higgs-TTS-3-4B'),
              pool.submit(model,'unsloth/Qwen3.5-9B-GGUF','Qwen3.5-9B-Q4_K_M.gguf','Qwen3.5-9B-Roles')]
        for job in jobs:job.result()
