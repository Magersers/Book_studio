"""Explicit actor sounds without changing the immutable book text.

This is deliberately not an emotion detector. The director/analyzer confirms
one performance for a character part. Only then can a leading laugh spelling
be replaced by its nonverbal sound; ordinary dialogue is left alone.
"""
import re

VERSION = 'drama3-performance-v1'
SUPPORTED = ('none', 'laughs', 'chuckles')
POINT_TAGS = {'laughs': '[laughs heartily]', 'chuckles': '[chuckles]'}
NARRATOR_NAMES = frozenset(('автор', 'рассказчик', 'повествователь', 'narrator', 'author',
                           'рассказчик (я)', 'автор (я)', 'я (рассказчик)'))
INSTRUCTION = '''Необязательное поле performance у части: none, laughs, chuckles. Это отдельный короткий актёрский звук, не настроение и не текст для чтения. Указывай laughs/chuckles ТОЛЬКО для подтверждённого контекстом смеха конкретного говорящего персонажа (например, автор прямо пишет «рассмеялся», «хохотнул»). Одно «Ха!» само по себе может быть удивлением или иронией и НЕ доказывает смех. «Ага», «Ха?», улыбка, усмешка, ухмылка, прищур и весёлое настроение не повод добавлять звук. Не назначай performance словам рассказчика, авторским описаниям, служебным частям или упоминаниям слова «ха-ха». Не убирай «рассмеялся/хохотнул» из авторского текста: они остаются у рассказчика. text/unit_id и исходную пунктуацию сохраняй; программа сама отдельно формирует произносимый текст и один нативный тег [laughs]/[chuckles]. Не складывай несколько эмоций или тегов в performance. При сомнении none.'''

# These spellings count only at the start of an explicitly directed turn,
# delimited as interjections. A name such as Хаханов or a quoted mention cannot
# match. There is intentionally no replacement elsewhere in the sentence.
_LAUGH = re.compile(r'(?i)^(?P<syllables>ха(?:[-\u2010-\u2015\s]*ха)*|хе(?:[-\u2010-\u2015\s]*хе)+|хех)'
                    r'(?![\w-])(?P<punct>[!.,…]+)(?P<space>\s*)')
_LAUGH_QUESTION = re.compile(r'(?i)^(?:ха(?:[-\u2010-\u2015\s]*ха)*|хе(?:[-\u2010-\u2015\s]*хе)+|хех)(?!\w)[!?.,…]*\?')
_CONTEMPLATION = re.compile(r'(?i)^хм+(?!\w)')
_TRAILING_LAUGH = re.compile(r'(?i)^(?:ха(?:[-\u2010-\u2015\s]*ха)*|хе(?:[-\u2010-\u2015\s]*хе)+|хех)\s*$')
_CONTROL = re.compile(r"^\[([A-Za-z][A-Za-z ,'-]{0,100})\]\s*")


def point_tag(action):
    if action not in POINT_TAGS:
        raise ValueError('Для актёрского звука нужен laughs или chuckles.')
    return POINT_TAGS[action]


def extend_schema(part):
    """Optional for backwards compatibility with previously stored markup."""
    part.setdefault('properties', {})['performance'] = dict(type='string', enum=list(SUPPORTED))
    return part


def validate_part(part):
    if not isinstance(part, dict):
        raise ValueError('Некорректная часть актёрской разметки.')
    performance = part.get('performance', 'none')
    if not isinstance(performance, str) or performance not in SUPPORTED:
        raise ValueError('performance: допустимы только none, laughs или chuckles.')
    if performance != 'none':
        speaker = part.get('speaker', '')
        if (not isinstance(speaker, str) or not speaker.strip()
                or speaker.strip().casefold() in NARRATOR_NAMES or part.get('kind', 'content') != 'content'):
            raise ValueError('Актёрский звук смеха допустим только в содержательной реплике персонажа.')
    return performance


def _dialogue_start(text):
    text = text.lstrip()
    # A dialogue dash is page typography, not a syllable to synthesize.
    if text.startswith(('—', '–')) or text.startswith('- '):
        text = text[1:].lstrip()
    return text


def render_text(part):
    """Return a separate Drama3 input; never mutate text, parts or source_text.

    With no confirmed metadata even literal Ха!/ха-ха stays unchanged. Existing
    leading directions in an explicit spoken_text stream are replaced by one
    point sound, so an old mood does not compete with the new actor action.
    """
    performance = validate_part(part)
    text = part.get('spoken_text', part.get('text', ''))
    if not isinstance(text, str):
        raise ValueError('Произносимый текст должен быть строкой.')
    if performance == 'none' or not text.strip():
        return text
    body = _dialogue_start(text)
    # Only a separate directed stream can contain old generic mood controls.
    # Literal brackets in original book text remain untouched.
    while True:
        control = _CONTROL.match(body)
        if not control or ('spoken_text' not in part and control[1] not in (*SUPPORTED[1:], 'laughs heartily')):
            break
        body = _dialogue_start(body[control.end():])
    # A question interjection is not rewritten into a laugh, even if an
    # overenthusiastic analyzer attached performance to this ambiguous turn.
    if _LAUGH_QUESTION.match(body) or _CONTEMPLATION.match(body):
        return text
    match = _LAUGH.match(body)
    if match:
        # Keep punctuation attached to the following words separate, but drop
        # punctuation belonging to the laugh syllables themselves.
        body = body[match.end():].lstrip()
    elif _TRAILING_LAUGH.fullmatch(body):
        body = ''
    tag = point_tag(performance)
    return tag + (' ' + body if body else '')


def _verbal_scaffold(text):
    """Punctuation and other model directions do not count as spoken words."""
    plain = re.sub(r'\[[^\]\n]*\]', '', text)
    return bool(re.search(r'[^\W_]', plain, flags=re.UNICODE))


def needs_inline_scaffold(part):
    action = validate_part(part)
    if action == 'none':
        return False
    rendered = render_text(part)
    tag = point_tag(action)
    return rendered.startswith(tag) and not _verbal_scaffold(rendered[len(tag):])


def actor_sound(part):
    """Protect the onset only when a safe directed input will actually be sent."""
    action = validate_part(part)
    if action == 'none':
        return False
    rendered = render_text(part)
    tag = point_tag(action)
    return rendered.startswith(tag) and _verbal_scaffold(rendered[len(tag):])


def render_items(part):
    """Production streams: never submit an unscaffolded actor tag to Drama3.

    Tag-only generations can invent speech. The renderer may first coalesce a
    source-adjacent plain turn by the same actor, but never across narration.
    Without that verbal scaffold keep the source interjection, without cues.
    """
    rendered = render_text(part)
    if actor_sound(part):
        return [dict(text=rendered, performance=part['performance'])]
    if needs_inline_scaffold(part):
        fallback = _dialogue_start(part.get('text', ''))
        while True:
            control = _CONTROL.match(fallback)
            if not control:
                break
            fallback = _dialogue_start(fallback[control.end():])
        return [dict(text=fallback)] if _verbal_scaffold(fallback) else []
    return [dict(text=rendered)] if rendered.strip() else []
