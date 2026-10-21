"""MDX lookup, redirects, and definition caching."""

import os
import re
import sqlite3
from collections import defaultdict

from ..context import config
from ..libs import MdxBuilder
from .helpers import export, service_wrap
from .local import LocalService, DictionaryNotReady
from .mdx_media import MdxMediaMixin
from .result import QueryResult


class MdxService(MdxMediaMixin, LocalService):
    def __init__(self, dict_path):
        binding = getattr(type(self), '__dict_binding__', None)
        if binding:
            from .dictionary_binding import resolve_dictionary
            dict_path = resolve_dictionary(binding['file'], binding['title'], dict_path)
        super(MdxService, self).__init__()
        self.dict_path = dict_path
        self.media_cache = defaultdict(set)
        self.cache = defaultdict(str)
        self.html_cache = defaultdict(str)
        self.query_interval = 0.01
        self.word_links = []
        self.styles = []
        if MdxService.check(self.dict_path):
            self.builder = self._get_builder(dict_path, service_wrap(MdxBuilder, dict_path))

    @staticmethod
    def check(dict_path):
        return os.path.isfile(dict_path) and dict_path.lower().endswith('.mdx')

    @property
    def support(self):
        return MdxService.check(self.dict_path)

    @property
    def title(self):
        if not self.builder or config.use_filename or not getattr(self.builder, '_title', None) or getattr(self.builder, '_title', '').startswith('Title'):
            return self._filename
        else:
            return self.builder._title

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
        html = self.get_default_html()
        js = re.findall(r'<script .*?>(.*?)</script>', html, re.DOTALL)
        jsfile = re.findall(r'<script .*?src=[\'\"](.+?)[\'\"]', html, re.DOTALL)
        return QueryResult(result=html, js=u'\n'.join(js), jsfile=jsfile)

    def _get_definition_mdx(self, word=None):
        if word is None: word = self.word
        ignorecase = config.ignore_mdx_wordcase and (word != word.lower() or word != word.upper())
        content = self.builder.mdx_lookup(word, ignorecase=ignorecase)
        str_content = ""
        if len(content) > 0:
            for c in content:
                str_content += c.replace("\r\n", "").replace("entry:/", "")
        return str_content

    def _get_definition_mdd(self, word):
        word = word.replace('/', '\\')
        ignorecase = config.ignore_mdx_wordcase and (word != word.lower() or word != word.upper())
        content = self.builder.mdd_lookup(word, ignorecase=ignorecase)
        if len(content) > 0: return [content[0]]
        return []

    def get_html(self, word=None):
        if word is None: word = self.word
        if not self.html_cache[word]:
            html = self._get_definition_mdx(word)
            if html: self.html_cache[word] = html
        return self.html_cache[word]

    def save_file(self, filepath_in_mdx, savepath):
        # Explicit destinations remain supported for existing custom scripts.
        try:
            if not os.path.isabs(savepath):
                savepath = self.media_name(filepath_in_mdx)
            bytes_list = self._get_definition_mdd(filepath_in_mdx)
            if bytes_list:
                path = self.media_path(savepath)
                if not os.path.exists(path):
                    with open(path, 'wb') as file:
                        file.write(bytes_list[0])
                return savepath
        except sqlite3.OperationalError:
            pass
        return ''

    def get_default_html(self):
        if not self.cache[self.word]:
            self.word_links = [self.word.upper()]
            self._get_default_html(self.word)
        return self.cache[self.word]

    def _get_default_html(self, word=None):
        html = u''
        if word is None: word = self.word
        result = self.get_html(word)
        if result:
            if result.upper().find(u"@@@LINK=") > -1:
                raw_html, _, result = result.partition("@@@LINK=")
                words = [i.strip() for i in filter(None, result.split('@@@LINK='))]
                html_list = [raw_html, ] if raw_html else []
                for redirect_word in words:
                    if not redirect_word.upper() in self.word_links:
                        self.word_links.append(redirect_word.upper())
                        html_list.append(self._get_default_html(redirect_word))
                if len(html_list) != 0:
                    html = "<br>".join(html_list)
            else:
                html = result
        self.cache[word] = self.adapt_to_anki(html)
        return html

    def _get_default_html_one_word(self):
        html = u''
        result = self.get_html()
        if result:
            if result.upper().find(u"@@@LINK=") > -1:
                word = result[len(u"@@@LINK="):].strip()
                if not word.upper() in self.word_links:
                    self.word_links.append(word.upper())
                    self.word = word
                    return self._get_default_html()
            html = self.adapt_to_anki(result)
        self.cache[self.word] = html
        return self.cache[self.word]
