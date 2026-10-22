"""Fetch the ten most-used public Russian voices per gender (metadata only)."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
API = 'https://api.fish.audio/model'


def fetch(gender, limit=10):
    query = urllib.parse.urlencode(dict(language='ru', tag=gender,
        sort_by='task_count', page_size=limit, page_number=1))
    request = urllib.request.Request(API+'?'+query, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        page = json.load(response)
    voices = []
    for item in page['items']:
        ident = item['_id']
        tags = item.get('tags', [])
        if (not re.fullmatch('[a-f0-9]{32}', ident) or gender not in tags
                or 'ru' not in item.get('languages', []) or item.get('visibility') != 'public'
                or item.get('dmca_taken_down') or item.get('state') != 'trained'):
            raise ValueError('Unexpected or unavailable catalogue entry: '+ident)
        voices.append(dict(id=ident, name=item['title'].strip(),
            description=item.get('description') or '', languages=item['languages'],
            gender=gender, age=next((t for t in tags if t in ('young','middle-aged','old')), ''),
            tags=tags, author=(item.get('author') or {}).get('nickname', ''),
            source_url='https://fish.audio/m/'+ident+'/',
            sample_url=next((s['audio'] for s in item.get('samples', []) if s.get('audio','').startswith('https://')), ''),
            task_count=item.get('task_count', 0), rank=len(voices)+1,
            licensed=item.get('licensed') is True))
    if len(voices) != limit:
        raise ValueError(f'Expected {limit} {gender} voices; got {len(voices)}')
    if [v['task_count'] for v in voices] != sorted((v['task_count'] for v in voices), reverse=True):
        raise ValueError('Popularity ordering changed')
    return voices


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'assets/voices/fish-audio-ru.json')
    args=parser.parse_args()
    voices=fetch('male')+fetch('female')
    if len({v['id'] for v in voices}) != len(voices):
        raise ValueError('Duplicate voice IDs between genders')
    payload=dict(version=1, fetched_at=datetime.now(timezone.utc).isoformat(),
        source_url=API, selection=dict(language='ru', per_gender=10,
        sort_by='task_count', description='Ten most-used male and ten most-used female public Russian voices; gender labels supplied by Fish Audio.'),
        total=len(voices), voices=voices)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Saved {len(voices)} voices to {args.output}')


if __name__ == '__main__':
    main()
