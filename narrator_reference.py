"""Optional curated narrator reference; original avatar recording remains intact."""
import hashlib,json
from pathlib import Path

def source_identity(reference,transcript):
    stat=Path(reference).stat()
    return dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns,transcript_sha256=hashlib.sha256(transcript.encode()).hexdigest())

def select(reference,transcript):
    reference=Path(reference).resolve();config=reference.parent/'narrator-anchor.json'
    if not config.is_file():return reference,transcript,None
    try:
        saved=json.loads(config.read_text(encoding='utf-8'))
        if saved.get('version')!=1 or saved.get('source')!=source_identity(reference,transcript):return reference,transcript,None
        filename=saved['file']
        if filename!=Path(filename).name:return reference,transcript,None
        anchor=reference.parent/filename;stat=anchor.stat()
        if saved.get('anchor')!={'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}:return reference,transcript,None
        if not isinstance(saved.get('transcript'),str) or not saved['transcript'].strip():return reference,transcript,None
        fingerprint=hashlib.sha256(config.read_bytes()).hexdigest()
        return anchor,saved['transcript'],fingerprint
    except (OSError,ValueError,KeyError,TypeError):return reference,transcript,None

