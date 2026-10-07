"""Streaming document readers. Return (text, is_heading), without opening external apps."""
import re
import zipfile
import codecs
from pathlib import Path
from defusedxml import ElementTree as ET

FORMATS = '*.pdf *.docx *.epub *.fb2 *.fb2.zip *.txt *.md *.rtf *.html *.htm *.odt *.mobi'
HEADING = re.compile(r'^(?:глава|часть|книга|том|chapter|part|book)\s+[\wIVXLCDM]+(?:\b|[.:])|^(?:пролог|эпилог|предисловие|послесловие|введение|заключение)\s*$', re.I)

def is_heading(text):
    return len(text)<160 and bool(HEADING.search(text.strip()))

def xml_blocks(stream):
    stack=[]
    for event, node in ET.iterparse(stream, events=('start','end')):
        tag=node.tag.rsplit('}',1)[-1].lower()
        if event=='start':
            stack.append(tag); continue
        if tag in ('p','h1','h2','h3','h4','h5','h6','h'):
            text=''.join(node.itertext()).strip()
            if text:
                yield text, tag!='p' or 'title' in stack or is_heading(text)
            node.clear()
        stack.pop()

def blocks(path, warnings, progress=lambda *a:None, check=lambda:None):
    path=Path(path); suffix=path.suffix.lower()
    if suffix in ('.pdf','.mobi'):
        import pymupdf
        with pymupdf.open(path) as document:
            if document.needs_pass:
                raise ValueError('Документ защищён паролем. Сохраните доступную копию.')
            empty=0
            toc={row[2]-1:row[1] for row in document.get_toc() if row[0]<=2}
            for index,page in enumerate(document):
                check()
                progress(0,f'Читаем страницу {index+1} / {len(document)}…')
                text=page.get_text('text',sort=True).strip()
                tessdata=Path(__file__).resolve().parent/'models/tessdata'
                if not text and suffix=='.pdf' and (tessdata/'rus.traineddata').exists() and (tessdata/'eng.traineddata').exists():
                    progress(0,f'OCR: распознаём страницу {index+1} / {len(document)}…')
                    text=page.get_text('text',textpage=page.get_textpage_ocr(language='rus+eng',dpi=200,full=True,tessdata=str(tessdata)),sort=True).strip()
                    if 'PDF содержит страницы, распознанные OCR: проверьте ошибки в тексте.' not in warnings:
                        warnings.append('PDF содержит страницы, распознанные OCR: проверьте ошибки в тексте.')
                if not text:
                    empty+=1; continue
                if index in toc:
                    yield toc[index], True
                    text=re.sub(r'^\s*'+re.escape(toc[index])+r'\s*\n','',text,count=1,flags=re.I)
                # Preserve dialogue and blank lines; join wrapped PDF prose.
                paragraph=''
                for line in text.splitlines():
                    line=line.strip()
                    if not line or is_heading(line) or line.startswith(('—','–','- ')):
                        if paragraph: yield paragraph,False; paragraph=''
                        if line: yield line,is_heading(line)
                    else:
                        paragraph += (' ' if paragraph else '')+line
                        if len(paragraph)>6000:
                            yield paragraph,False; paragraph=''
                if paragraph: yield paragraph,False
            if empty:
                warnings.append(f'{empty} страниц без текстового слоя пропущено. Для сканов сначала нужен OCR.')
    elif suffix=='.docx':
        with zipfile.ZipFile(path) as archive, archive.open('word/document.xml') as stream:
            ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            for _,node in ET.iterparse(stream,events=('end',)):
                if node.tag==ns+'p':
                    text=''.join(n.text or '' for n in node.iter(ns+'t')).strip()
                    style=node.find('.//'+ns+'pStyle')
                    heading=style is not None and re.search(r'heading|заголовок',style.get(ns+'val',''),re.I)
                    if text: yield text,bool(heading) or is_heading(text)
                    node.clear()
    elif suffix=='.epub':
        with zipfile.ZipFile(path) as archive:
            container=ET.fromstring(archive.read('META-INF/container.xml'))
            opf=next(n.get('full-path') for n in container.iter() if n.tag.endswith('rootfile'))
            package=ET.fromstring(archive.read(opf))
            manifest={n.get('id'):n for n in package.iter() if n.tag.endswith('}item')}
            import posixpath
            from urllib.parse import unquote
            for node in package.iter():
                if node.tag.endswith('}itemref') and node.get('linear','yes')!='no':
                    item=manifest[node.get('idref')]
                    if 'nav' in item.get('properties','').split(): continue
                    member=posixpath.normpath(posixpath.join(posixpath.dirname(opf),unquote(item.get('href').split('#')[0])))
                    with archive.open(member) as stream:
                        yield from xml_blocks(stream)
    elif suffix=='.fb2':
        with path.open('rb') as stream: yield from xml_blocks(stream)
    elif suffix=='.zip' and path.name.lower().endswith('.fb2.zip'):
        with zipfile.ZipFile(path) as archive:
            names=[n for n in archive.namelist() if n.lower().endswith('.fb2')]
            if len(names)!=1: raise ValueError('Архив должен содержать одну книгу FB2.')
            with archive.open(names[0]) as stream: yield from xml_blocks(stream)
    elif suffix=='.odt':
        with zipfile.ZipFile(path) as archive, archive.open('content.xml') as stream:
            yield from xml_blocks(stream)
    elif suffix in ('.txt','.md'):
        with path.open('rb') as file: sample=file.read(65536)
        encoding='utf-16' if sample.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig'
        try: codecs.getincrementaldecoder(encoding)().decode(sample,final=False)
        except UnicodeDecodeError: encoding='cp1251'
        with path.open(encoding=encoding) as file:
            paragraph=''
            for line in file:
                line=line.strip()
                heading=is_heading(line.lstrip('# ')) or (suffix=='.md' and line.startswith('#'))
                if not line or heading or line.startswith(('—','–','- ')):
                    if paragraph: yield paragraph,False; paragraph=''
                    if line: yield line.lstrip('# ').strip() if suffix=='.md' else line,heading
                else:
                    paragraph+=(' ' if paragraph else '')+line
                    if len(paragraph)>6000: yield paragraph,False; paragraph=''
            if paragraph: yield paragraph,False
    elif suffix in ('.html','.htm','.rtf'):
        raw=path.read_bytes()
        try: text=raw.decode('utf-8-sig')
        except UnicodeDecodeError: text=raw.decode('cp1251')
        if suffix=='.rtf':
            from striprtf.striprtf import rtf_to_text
            text=rtf_to_text(text)
        else:
            from bs4 import BeautifulSoup
            soup=BeautifulSoup(text,'html.parser')
            for n in soup(['script','style','nav']): n.decompose()
            text=soup.get_text('\n')
        for line in text.splitlines():
            if line.strip(): yield line.strip(),is_heading(line)
    else:
        raise ValueError('Формат не поддерживается. Старый DOC, AZW и защищённые книги сохраните как DOCX, EPUB или TXT.')
