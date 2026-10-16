"""Styling remains opt-in and never replaces user-owned card CSS."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import test_modularization as support


class AIFormatTests(unittest.TestCase):
    def setUp(self):
        self.host = support.RefactorTests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)
        self.format = self.host.load('utils.ai_format')

    def test_default_output_remains_unstyled_and_raw_text_is_escaped(self):
        self.assertEqual(self.format.render('**a**'), '<p><strong>a</strong></p>')
        self.assertEqual(self.format.render('**a**\n<script>x</script>', False),
                         '**a**<br>&lt;script&gt;x&lt;/script&gt;')
        self.assertFalse(self.format.style_for(SimpleNamespace(), 1).get('enabled', False))

    def test_styled_types_have_classes_and_preserve_links_and_safe_html(self):
        value = self.format.render('# Concept\n\n| A | B |\n| --- | --- |\n| x | y |\n\n> quote\n\n[link](https://example.com)\n\n```\n<script>x</script>\n```', classes=True)
        for name in ('fwq-ai', 'fwq-heading', 'fwq-table', 'fwq-quote', 'fwq-link', 'fwq-code'):
            self.assertIn('class="' + name + '"', value)
        self.assertIn('href="https://example.com"', value)
        self.assertNotIn('<script>', value)

    def test_second_injection_is_noop_and_detection_is_limited_to_owned_block(self):
        original = '.card { color: red; }\n.custom .fwq-table { width: 40%; }\n  '
        first = self.format.inject_css(original, self.format.DEFAULT_CSS)
        self.assertTrue(first.startswith(original))
        self.assertIn('width: 100%', first)
        self.assertEqual(first.count(self.format.START), 1)
        self.assertEqual(self.format.inject_css(first, self.format.DEFAULT_CSS), first)

    def test_comments_values_and_class_prefixes_do_not_count_as_existing_rules(self):
        original = '/* .fwq-quote {} */\n.card { content: ".fwq-code"; }\n.fwq-table-old { color: red; }'
        value = self.format.inject_css(original, self.format.DEFAULT_CSS)
        self.assertIn('.fwq-ai .fwq-quote {', value)
        self.assertIn('.fwq-ai .fwq-code {', value)
        self.assertIn('.fwq-ai .fwq-table {', value)

    def test_class_rules_inside_media_queries_are_detected(self):
        css = self.format.START + '\n@media (max-width: 500px) { .fwq-table { color: blue; } }\n' + self.format.END
        injected = self.format.inject_css(css, self.format.DEFAULT_CSS)
        self.assertNotIn('width: 100%', injected)

    def test_missing_class_is_restored_without_replacing_manual_edits_in_owned_block(self):
        first = self.format.inject_css('.card { color: red; }', self.format.DEFAULT_CSS)
        first = first.replace('line-height: 1.6', 'line-height: 1.9')
        import re
        partial = re.sub(r'\.fwq-ai \.fwq-quote \{[^}]*\}\n', '', first)
        repaired = self.format.inject_css(partial, self.format.DEFAULT_CSS)
        self.assertIn('line-height: 1.9', repaired)
        self.assertEqual(repaired.count('.fwq-ai .fwq-quote {'), 1)
        self.assertEqual(repaired.count(self.format.START), 1)
        self.assertEqual(self.format.inject_css(repaired, self.format.DEFAULT_CSS), repaired)

    def test_edit_and_disable_touch_only_managed_block_and_skip_duplicate_writes(self):
        original = '.card { color: red; }\n.custom .fwq-table { width: 40%; }'
        model = {'id': 1, 'name': 'Test', 'css': original}
        models = Mock()
        models.get.side_effect = lambda mid: dict(model)
        def update(value):
            model.update(value)
            return 'changes'
        models.update_dict.side_effect = update
        self.format.save_style(models, 1, self.format.DEFAULT_CSS, True)
        self.format.save_style(models, 1, self.format.DEFAULT_CSS, True)
        self.assertEqual(models.update_dict.call_count, 1)
        new = self.format.DEFAULT_CSS.replace('line-height: 1.6', 'line-height: 1.8')
        self.format.save_style(models, 1, new, True, replace=True)
        self.assertIn('line-height: 1.8', model['css'])
        self.assertTrue(model['css'].startswith(original))
        self.format.save_style(models, 1, new, False)
        self.assertEqual(model['css'], original)
        self.format.save_style(models, 1, new, False)
        self.assertEqual(models.update_dict.call_count, 3)

    def test_css_scope_and_syntax_errors_do_not_change_models(self):
        models = Mock()
        models.get.return_value = {'id': 1, 'css': '.card {}'}
        for bad in ('.card { color: red; }', '.fwq-ai + .card { color: red; }',
                    '.fwq-ai {', '@import url(x);', '@media screen { .fwq-ai {} }'):
            with self.subTest(css=bad), self.assertRaises(ValueError):
                self.format.save_style(models, 1, bad, True)
        models.update_dict.assert_not_called()

    def test_connection_freezes_formatting_by_note_type(self):
        self.host.config.ai_markdown = False
        self.host.config.ai_styles = {'1': {'enabled': True}, '2': {'enabled': False}}
        ai = self.host.load('service.ai')
        self.assertFalse(ai.snapshot_connection('ai:missing', 1).classes)
        self.host.config.ai_css_enabled = True
        first = ai.snapshot_connection('ai:missing', 1)
        second = ai.snapshot_connection('ai:missing', 2)
        self.host.config.ai_markdown = True
        self.host.config.ai_styles['1']['enabled'] = False
        self.assertFalse(first.markdown)
        self.assertTrue(first.classes)
        self.assertFalse(second.classes)

    def test_legacy_marked_css_is_updated_in_place_after_rebranding(self):
        old = '.card { color: red; }\n\n/* FastWQ AI styles: begin */\n.fwq-ai { color: blue; }\n/* FastWQ AI styles: end */'
        model = {'id': 1, 'css': old}
        models = Mock()
        models.get.side_effect = lambda mid: dict(model)
        models.update_dict.side_effect = lambda value: model.update(value)
        settings = SimpleNamespace(ai_css_enabled=True, ai_styles={'1': {'enabled': True}}, ai_css=self.format.DEFAULT_CSS)
        self.format.apply_written_style(models, 1, settings)
        self.assertIn(self.format.START, model['css'])
        self.assertNotIn('FastWQ AI styles', model['css'])
        self.assertTrue(model['css'].startswith('.card { color: red; }'))
        self.format.apply_written_style(models, 1, settings)
        self.assertEqual(models.update_dict.call_count, 1)
