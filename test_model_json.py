import json,unittest
from model_json import parse
class JsonTest(unittest.TestCase):
    def test_extra_array_closer_before_object_field(self):
        self.assertEqual(parse('{"characters":[{"portrait":{"state":"спокоен"}],"note":""}]}'),{'characters':[{'portrait':{'state':'спокоен'},'note':''}]})
    def test_missing_portrait_closer_before_assignments(self):
        value='{"characters":[{"name":"Ли Фань","portrait":{"state":"спокоен"}],"assignments":[],"summary":"День рождения."}'
        parsed=parse(value)
        self.assertEqual(parsed['characters'][0]['portrait']['state'],'спокоен')
        self.assertEqual(parsed['assignments'],[])
    def test_valid_json_and_string_brackets_unchanged(self):
        value={'a':['a}],"x": «слова»',{'b':2}]}
        self.assertEqual(parse(json.dumps(value)),value)
    def test_truncated_or_ambiguous_response_is_rejected(self):
        for value in ('{"a":','{"a":[1}', '{"text":"неэкранированная "цитата""}'):
            with self.assertRaises(json.JSONDecodeError):parse(value)
