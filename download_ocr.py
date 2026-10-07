from pathlib import Path
import urllib.request
ROOT=Path(__file__).resolve().parent
folder=ROOT/'models/tessdata'; folder.mkdir(parents=True,exist_ok=True)
for language in ('rus','eng'):
    target=folder/(language+'.traineddata')
    if not target.exists():
        temporary=target.with_suffix('.part')
        urllib.request.urlretrieve('https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/'+target.name,temporary)
        if temporary.stat().st_size<100000: raise RuntimeError('Incomplete OCR language download')
        temporary.replace(target)
    print('OCR:',target.name)
