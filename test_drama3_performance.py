import copy
import unittest

import drama3_performance as performance


class PerformanceTests(unittest.TestCase):
    def part(self, text, action='none', **fields):
        return dict(text=text, speaker='Рик', kind='content', performance=action, **fields)

    def test_no_automatic_replacement_without_context_confirmation(self):
        for text in ('— Ха! Ты угадал.', 'Ха-ха, смешно.', 'Хехе.', 'Хахаха!', 'Ха?',
                     'Ага, понял.', 'Хаханов пришёл.', 'Он произнёс слово «хахаха».',
                     '«Ха-ха» — странное слово.', 'Она усмехнулась.', 'Рик рассмеялся:'):
            with self.subTest(text=text):
                self.assertEqual(performance.render_text(self.part(text)), text)

    def test_confirmed_single_interjection_becomes_real_laugh(self):
        self.assertEqual(performance.render_text(self.part('— Ха! Парень, ты что, мысли читаешь?', 'laughs')),
                         '[laughs heartily] Парень, ты что, мысли читаешь?')

    def test_confirmed_repeated_interjections_and_sound_only(self):
        for text in ('Ха-ха! Вот это да.', 'Ха ха… Вот это да.', 'Хахаха, Вот это да.', 'Хехе. Вот это да.'):
            with self.subTest(text=text):
                self.assertEqual(performance.render_text(self.part(text,'chuckles')), '[chuckles] Вот это да.')
        self.assertEqual(performance.render_text(self.part('Ха!', 'laughs')), '[laughs heartily]')
        self.assertEqual(performance.render_text(self.part('Хехе', 'chuckles')), '[chuckles]')

    def test_explicit_context_can_add_sound_without_rewriting_dialogue(self):
        text='В точку. Но давать еду и одеяло — это грабёж.'
        self.assertEqual(performance.render_text(self.part(text, 'chuckles')), '[chuckles] '+text)

    def test_surprise_question_never_becomes_laugh(self):
        for text in ('Ха?', '— Ха?! Ты серьёзно?', 'Ха-ха? Это вопрос.'):
            self.assertEqual(performance.render_text(self.part(text,'laughs')), text)

    def test_contemplation_is_not_converted_even_with_bad_metadata(self):
        for text in ('Хм… надо подумать.', '— Хмм, интересно.', 'Хм?'):
            self.assertEqual(performance.render_text(self.part(text,'laughs')),text)

    def test_names_agreement_and_mentions_are_not_consumed(self):
        for text in ('Ага, значит, паладин.', 'Хаханов пришёл.', 'Я сказал «ха-ха».',
                     '«Ха-ха» — это название.', 'Ха-ха — странное слово.'):
            # An explicit actor action may precede arbitrary dialogue. It must
            # never erase these lexical words or quoted descriptions.
            self.assertEqual(performance.render_text(self.part(text,'chuckles')), '[chuckles] '+text)

    def test_source_is_immutable_and_spoken_numbers_are_retained(self):
        original=self.part('— Ха! Все 3 карты?', 'laughs',
                           source_text='— Ха! Все 3 карты?', spoken_text='[surprised] Ха! Все три карты?')
        saved=copy.deepcopy(original)
        self.assertEqual(performance.render_text(original),'[laughs heartily] Все три карты?')
        self.assertEqual(original,saved)

    def test_single_point_tag_replaces_old_compound_mood_directions(self):
        original=self.part('В точку.', 'chuckles', spoken_text='[firm] [happy, delighted] В точку.')
        rendered=performance.render_text(original)
        self.assertEqual(rendered,'[chuckles] В точку.')
        self.assertEqual(rendered.count('['),1)
        self.assertEqual(performance.render_text(self.part('Ха!', 'laughs', spoken_text='[laughs] Ха!')),'[laughs heartily]')

    def test_original_brackets_are_not_arbitrarily_discarded(self):
        self.assertEqual(performance.render_text(self.part('[Chapter One] я прочёл это.', 'laughs')),
                         '[laughs heartily] [Chapter One] я прочёл это.')

    def test_production_never_sends_tag_only_or_punctuation_scaffold(self):
        for text in ('Ха!', 'Ха! ...', 'Ха! [firm]', '[laughs]'):
            part=self.part(text,'laughs')
            self.assertTrue(performance.needs_inline_scaffold(part))
            self.assertFalse(performance.actor_sound(part))
            self.assertTrue(all('performance' not in item and not item['text'].startswith('[laughs')
                                for item in performance.render_items(part)))

    def test_production_inline_point_has_verbal_scaffold_and_event_metadata(self):
        part=self.part('Ха! Ты угадал.','laughs')
        self.assertEqual(performance.render_items(part),[dict(text='[laughs heartily] Ты угадал.',performance='laughs')])
        self.assertTrue(performance.actor_sound(part))
        self.assertFalse(performance.needs_inline_scaffold(part))
        self.assertFalse(performance.actor_sound(self.part('Хм… нет.','laughs')))

    def test_long_confirmed_laugh_spelling_is_consumed_completely(self):
        part=self.part('Ха-ха-ха-ха-ха-ха-ха! Смешно.','laughs')
        self.assertEqual(performance.render_text(part),'[laughs heartily] Смешно.')

    def test_narrator_and_service_parts_cannot_have_actor_action(self):
        for speaker in ('', 'Рассказчик', 'narrator', 'Автор'):
            with self.assertRaises(ValueError):
                performance.validate_part(dict(text='Он рассмеялся.',speaker=speaker,performance='laughs'))
        for kind in ('label','book_title','toc','credits','sound'):
            with self.assertRaises(ValueError):
                performance.validate_part(dict(text='Ха!',speaker='Рик',kind=kind,performance='laughs'))
        self.assertEqual(performance.render_text(dict(text='Он рассмеялся.',speaker='')),'Он рассмеялся.')

    def test_metadata_is_optional_and_bounded(self):
        self.assertEqual(performance.validate_part(dict(text='Привет.',speaker='Рик')),'none')
        for value in (None,True,1,[],{},'laughing','sarcastic','laughs,chuckles','[laughs]'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                performance.validate_part(dict(text='Привет.',speaker='Рик',performance=value))

    def test_optional_schema_does_not_break_existing_fields(self):
        schema=dict(type='object',properties=dict(text=dict(type='string')),required=['text'])
        performance.extend_schema(schema)
        self.assertEqual(schema['required'],['text'])
        self.assertEqual(schema['properties']['performance']['enum'],['none','laughs','chuckles'])


if __name__=='__main__':unittest.main()
