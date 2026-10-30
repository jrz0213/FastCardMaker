"""Topic edits must preserve identity and reject ambiguous AI changes."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('topic_plan', Path(__file__).resolve().parents[1] / 'src/service/topic_plan.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def card(topic):
    return {'topic': topic, 'content': 'Material'}


class TopicPlanTests(unittest.TestCase):
    def setUp(self):
        self.cards, self.counter = module.apply_changes([], [{'action': 'add', 'cards': [card('A'), card('B'), card('C')]}], 1)

    def test_merge_keeps_target_and_appends_new_cards(self):
        result, counter = module.apply_changes(self.cards, [
            {'action': 'add', 'cards': [card('D')]},
            {'action': 'replace', 'id': 2, 'cards': [card('B+C')]},
            {'action': 'delete', 'id': 3}], self.counter, [2, 3])
        self.assertEqual([c['id'] for c in result], [1, 2, 4])
        self.assertEqual(result[1]['created_at'], self.cards[1]['created_at'])
        self.assertEqual(counter, 5)
        self.assertEqual(len(self.cards), 3)

    def test_reserved_identifiers_survive_discard_and_restore(self):
        _, reserved = module.apply_changes(self.cards, [{'action': 'add', 'cards': [card('discarded')]}], self.counter)
        result, _ = module.apply_changes(self.cards, [{'action': 'add', 'cards': [card('new')]}], reserved)
        self.assertEqual(result[-1]['id'], 5)

    def test_insert_preserves_identity_and_creation_order(self):
        result, counter = module.apply_changes(self.cards, [
            {'action': 'replace', 'id': 2, 'cards': [card('B expanded')]},
            {'action': 'add', 'after_id': 2, 'cards': [card('B part two'), card('B part three')]},
        ], self.counter, [2])
        self.assertEqual([c['id'] for c in result], [1, 2, 4, 5, 3])
        self.assertEqual(counter, 6)

    def test_invalid_changes_are_rejected(self):
        cases = [
            [{'action': 'delete', 'id': 99}],
            [{'action': 'replace', 'id': 2, 'cards': []}],
            [{'action': 'add', 'id': 3, 'cards': [card('bad')]}],
            [{'action': 'delete', 'id': 2}, {'action': 'delete', 'id': 2}],
            [{'action': 'delete', 'id': 1}],
        ]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                module.apply_changes(self.cards, changes, self.counter, [2])


if __name__ == '__main__':
    unittest.main()
