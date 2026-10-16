"""StarDict lookup and text conversion."""

import os

from ..context import config
from ..libs import StardictBuilder
from .helpers import export, service_wrap
from .local import LocalService, DictionaryNotReady
from .result import QueryResult


class StardictService(LocalService):
    def __init__(self, dict_path):
        super(StardictService, self).__init__()
        self.dict_path = dict_path
        self.query_interval = 0.05
        if StardictService.check(self.dict_path):
            dict_path = dict_path[:-4]
            self.builder = self._get_builder(dict_path, service_wrap(StardictBuilder, dict_path, in_memory=False))

    @staticmethod
    def check(dict_path): return os.path.isfile(dict_path) and dict_path.lower().endswith('.ifo')

    @property
    def support(self): return StardictService.check(self.dict_path)

    @property
    def title(self):
        if not self.builder or config.use_filename or not getattr(self.builder.ifo, 'bookname', None): return self._filename
        else: return self.builder.ifo.bookname

    def active(self, fld_ord, word):
        if self.builder is None:
            self.builder = self._get_builder(self.dict_path)
        status = self.get_db_status(self.dict_path)
        if status in ('checking', 'building') or self.builder is None:
            raise DictionaryNotReady(status)

        self.missed_css.clear()
        return super(LocalService, self).active(fld_ord, word)

    @export([u'默认', u'Default'])
    def fld_whole(self):
        try:
            result = self.builder[self.word]
            result = result.strip().replace('\r\n', '<br />').replace('\r', '<br />').replace('\n', '<br />')
            return QueryResult(result=result)
        except KeyError:
            return QueryResult.default()
