"""Build a clean, allowlisted Windows source package and a bootstrap installer."""
import hashlib,json,os,re,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def files():
    result=[]
    for name in json.loads((ROOT/'distribution.json').read_text(encoding='utf-8')):
        path=ROOT/name
        if not path.is_file():raise FileNotFoundError(name)
        if path.suffix in ('.py','.json','.md','.ps1','.yml','.cmd','.txt','.cs'):
            content=path.read_text(encoding='utf-8-sig')
            if re.search(r'\bsk-[a-zA-Z0-9]{24,}',content):raise ValueError('Possible credential in '+name)
            if re.search(r'[A-Za-z]:[\\/]Users[\\/][^\\/\s]+',content):raise ValueError('Personal path in '+name)
        result.append(path)
    return result

def build():
    out=ROOT/'dist';out.mkdir(exist_ok=True)
    archive=out/'BookStudio-source.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for path in files():z.write(path,path.relative_to(ROOT).as_posix())
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    exe=out/'BookStudio-Setup.exe'
    subprocess.run([str(compiler),'/nologo','/target:winexe','/optimize+',f'/out:{exe}',
        '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',
        '/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll',
        f'/resource:{archive},BookStudio.Source.zip',f'/win32icon:{ROOT / "assets/vox-studio.ico"}',str(ROOT/'tools/Installer.cs')],check=True)
    (out/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in (archive,exe)),encoding='ascii')
    print('Built',archive,exe)

if __name__=='__main__':build()
