"""Batch note UI labels must exist in English and Japanese with intact placeholders."""
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'src'
spec = importlib.util.spec_from_file_location('note_creator_i18n', ROOT / 'i18n.py')
i18n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(i18n)


class NoteCreatorLocaleTests(unittest.TestCase):
    def test_names_and_errors_are_translated(self):
        keys = ['AI 批量制卡', '笔记类型:', '内容类型', '主题讲解', '问答', '插件设置',
                '预览并添加笔记', '历史对话', '查看所有主题', '查看所有问答',
                'AI 流式连接中断，回复未完整生成。', 'AI 流式回复失败或未完整生成。',
                'AI 回复未完成文本生成。', '记录无法删除，请检查文件权限。']
        for locale in ('en', 'ja'):
            for key in keys:
                with self.subTest(locale=locale, key=key):
                    self.assertIn(key, i18n.catalog(locale))
                    self.assertNotEqual(i18n.translate(key, locale=locale), key)

    def test_count_placeholders_match(self):
        keys = ['全部历史对话（共 %s 条）', '当前共有 %s 个主题，以下按制卡顺序显示当前采用的版本。',
                '确定删除这 %s 条记录？当前打开的对话会继续保留。',
                '已切换为 #%s-%s，当前采用的内容如下。']
        for locale in ('en', 'ja'):
            for key in keys:
                with self.subTest(locale=locale, key=key):
                    self.assertEqual(re.findall(r'%[sd]', key), re.findall(r'%[sd]', i18n.translate(key, locale=locale)))


if __name__ == '__main__':
    unittest.main()
