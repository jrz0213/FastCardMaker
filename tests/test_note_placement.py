import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('note_placement', Path(__file__).resolve().parents[1] / 'src/service/note_placement.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PlacementTests(unittest.TestCase):
    def test_separate_targets_override_ai_and_dictionary(self):
        result = module.build_mappings([('Title', 'ai:one', 'old'), ('Body', 'dictionary', ''),
                                        ('Extra', 'ai:two', 'Explain')], 'Title', 'Body', 'Use')
        self.assertEqual([r['dict_unique'] for r in result], ['', '', 'ai:two'])
        self.assertTrue(all(r['ignore'] for r in result[:2]))
        self.assertFalse(result[2]['ignore'])
        self.assertIn('{{Body}}', result[2]['ai_prompt'])
        self.assertEqual(result[0]['ai_prompt'], 'old')

    def test_shared_target_locks_only_one_field(self):
        rows = [('Title', 'ai:one', ''), ('Extra', 'ai:two', 'Explain')]
        result = module.build_mappings(rows, 'Title', 'Title', 'Use')
        self.assertEqual(sum(bool(r['ignore']) for r in result), 1)
        self.assertEqual(result[1]['ai_prompt'].count('{{Title}}'), 1)
        self.assertEqual(rows[0][1], 'ai:one')

    def test_modes_skip_other_sources_even_when_configured(self):
        rows = [('Title', 'ai:locked', ''), ('Body', 'dict-locked', ''),
                ('AI', 'ai:one', 'Explain'), ('Dictionary', 'dict-one', '')]
        for mode, expected in [('ai', ['', '', 'ai:one', '']),
                               ('dictionary', ['', '', '', 'dict-one']),
                               ('both', ['', '', 'ai:one', 'dict-one'])]:
            with self.subTest(mode=mode):
                result = module.build_mappings(rows, 'Title', 'Body', 'Use', mode)
                self.assertEqual([m['dict_unique'] for m in result], expected)
                self.assertEqual(result[3]['ai_prompt'], '')


if __name__ == '__main__':
    unittest.main()
