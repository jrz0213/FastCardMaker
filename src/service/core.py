"""Common dictionary interface, exported fields, and query cache."""

import inspect
import re
import urllib.parse
from collections import defaultdict

from ..context import config
from ..utils.logger import logger
from .result import QueryResult
from ..utils.media import media_directory, media_path


class Service(object):
    def __init__(self):
        self.media_dir = media_directory()
        self.cache = defaultdict(defaultdict)
        self._unique = self.__class__.__name__
        self._exporters = self._get_exporters()
        self._fields, self._actions = zip(*self._exporters) if self._exporters else (None, None)
        self._word = ''
        self.query_interval = 0.5

    def media_path(self, filename):
        return media_path(filename, self.media_dir)

    def cache_this(self, result):
        self.cache[self.word].update(result)
        return result

    def cached(self, key):
        return (self.word in self.cache) and (key in self.cache[self.word])

    def cache_result(self, key):
        return self.cache[self.word].get(key, u'')

    def _get_from_api(self):
        return {}

    def _get_field(self, key, default=u''):
        return self.cache_result(key) if self.cached(key) else self._get_from_api().get(key, default)

    @property
    def unique(self):
        return self._unique

    @unique.setter
    def unique(self, value):
        self._unique = value

    @property
    def word(self):
        return self._word

    @word.setter
    def word(self, value):
        value = re.sub(r'</?\w+[^>]*>', '', value)
        self._word = value

    @property
    def quote_word(self):
        return urllib.parse.quote(self.word)

    @property
    def support(self):
        return True

    @property
    def fields(self):
        return self._fields

    @property
    def actions(self):
        return self._actions

    @property
    def exporters(self):
        return self._exporters

    def _get_exporters(self):
        flds = dict()
        methods = inspect.getmembers(self, predicate=inspect.ismethod)
        indexes_map = getattr(self.__class__, '__export_indexes__', {})
        for method_name, method_func in methods:
            export_attrs = getattr(method_func, '__export_attrs__', None)
            if export_attrs:
                label = export_attrs[0]
                index = indexes_map.get(method_name, export_attrs[1])
                flds.update({int(index): (label, method_func)})
        sorted_flds = sorted(flds)
        return [flds[key] for key in sorted_flds]

    def active(self, fld_ord, word):
        self.word = word
        dict_title = getattr(self, 'title', self.unique)

        logger.info(f"[查词起点] 接收请求 | 词典: [{dict_title}] | 目标单词: [{word}] | 请求字段序号: [{fld_ord}]")
        if fld_ord >= 0 and fld_ord < len(self.actions):
            field_name = self.fields[fld_ord]
            logger.info(f"[查词分发] 将交由解析器处理 | 提取字段: [{field_name}]")
            res = self.actions[fld_ord]()
            content_str = res.get('result', '') if isinstance(res, QueryResult) else str(res)
            logger.info(f"[查词终点] 流程完成 | 返回长度: {len(content_str)} 字符")
            return res

        logger.warning(f"[查词异常] 请求的字段序号无效或越界，强制返回空值 | 序号: {fld_ord}")
        return QueryResult.default()

    @staticmethod
    def get_anki_label(filename, type_):
        formats = {'audio': config.sound_str, 'img': u'<img src="{0}">', 'video': u'<video controls="controls" width="100%" height="auto" src="{0}"></video>'}
        return formats[type_].format(filename)
