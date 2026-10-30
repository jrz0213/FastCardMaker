import importlib.util
from pathlib import Path
import unittest
from copy import deepcopy

spec = importlib.util.spec_from_file_location('topic_draft', Path(__file__).resolve().parents[1] / 'src/service/topic_draft.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.card = dict(id=1, topic='A', content='B', created_at='now', version=1)
        self.data = dict(cards=[self.card], history=[], versions={'1': [self.card]}, next_id=2, count=1)

    def test_validated_copy_does_not_mutate_source(self):
        result = module.validate_draft(self.data)
        result['cards'][0]['topic'] = 'changed'
        self.assertEqual(self.data['cards'][0]['topic'], 'A')

    def test_rejects_corruption_before_publication(self):
        changes = [dict(versions=[]), dict(versions={'2': [self.card]}),
                   dict(cards=[self.card, self.card]), dict(count='1'),
                   dict(field_positions={'1': None}), dict(added_ids=['1']),
                   dict(history=[dict(role='assistant', content='x', topic_cards=[dict(id=1)])])]
        for change in changes:
            original = deepcopy(self.data)
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.validate_draft(dict(self.data, **change))
            self.assertEqual(self.data, original)


if __name__ == '__main__':
    unittest.main()
