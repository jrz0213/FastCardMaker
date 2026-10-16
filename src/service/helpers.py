"""Service registration, HTML parsing, styles, and resource naming."""

import inspect
import os
import random
import re
import shutil
import threading as _threading
import urllib.parse
from functools import wraps
from hashlib import sha1

from bs4 import BeautifulSoup

from ..lang import _cl
from ..utils import wrap_css
from ..utils.logger import logger
from .result import QueryResult
from ..utils.media import media_path


def sanitize_to_safe_encoding(filename):
    """
    将文件名转换为 Anki 和 HTML 双端绝对安全的编码格式，
    同时保留唯一性，不发生破坏性合并。
    """
    decoded = urllib.parse.unquote(filename)
    basename = os.path.basename(decoded.replace('\\', os.path.sep))

    mapping = {
        ' ': '-', '#': '_', '&': '_and_', '+': '_plus_', '=': '_eq_'
    }
    for k, v in mapping.items():
        basename = basename.replace(k, v)

    def safe_hex_encode(match):
        return f"_x{ord(match.group(0)):02X}_"

    # 仅允许：字母、数字、中文、点(.)、中划线(-)、下划线(_)
    safe_name = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5\.\-_]', safe_hex_encode, basename)
    return safe_name

def get_hex_name(prefix, val, suffix):
    ''' get sha1 hax name '''
    hex_digest = sha1(val.encode('utf-8')).hexdigest().lower()
    name = '.'.join(
        ['-'.join([prefix, hex_digest[:8], hex_digest[8:16], hex_digest[16:24], hex_digest[24:32], hex_digest[32:], ]),
         suffix, ])
    return name

def _is_method_or_func(object):
    return inspect.isfunction(object) or inspect.ismethod(object)

def register(labels):
    def _deco(cls):
        cls.__register_label__ = _cl(labels)
        methods = inspect.getmembers(cls, predicate=_is_method_or_func)
        exports = []
        for method_name, method_func in methods:
            attrs = getattr(method_func, '__export_attrs__', None)
            if attrs:
                exports.append((getattr(method_func, '__def_index__', 0), method_name, method_func))
        exports = sorted(exports)
        cls.__export_indexes__ = {}
        for index, item in enumerate(exports):
            method_name = item[1]
            cls.__export_indexes__[method_name] = index
        logger.info(f"成功注册词典服务类: [{cls.__name__}] | 标签: [{cls.__register_label__}] | 共绑定导出字段: {len(exports)} 个")
        return cls
    return _deco

def export(labels):
    def _with(fld_func):
        @wraps(fld_func)
        def _deco(self, *args, **kwargs):
            res = fld_func(self, *args, **kwargs)
            return QueryResult(result=res) if not isinstance(res, QueryResult) else res
        _deco.__export_attrs__ = [_cl(labels), -1]
        _deco.__def_index__ = export.EXPORT_INDEX
        export.EXPORT_INDEX += 1
        return _deco
    return _with
export.EXPORT_INDEX = 0

def copy_static_file(filename, new_filename=None, static_dir='static'):
    abspath = os.path.join(os.path.dirname(os.path.realpath(__file__)), static_dir, filename)
    shutil.copy(abspath, media_path(new_filename if new_filename else filename))

def with_styles(**styles):
    def _with(fld_func):
        @wraps(fld_func)
        def _deco(cls, *args, **kwargs):
            res = fld_func(cls, *args, **kwargs)
            cssfile, css, jsfile, js, need_wrap_css, class_wrapper = \
                styles.get('cssfile', None), styles.get('css', None), \
                styles.get('jsfile', None), styles.get('js', None), \
                styles.get('need_wrap_css', False), styles.get('wrap_class', '')

            def wrap(html, css_obj, is_file=True):
                if need_wrap_css and class_wrapper:
                    html = u'<div class="{}">{}</div>'.format(class_wrapper, html)
                    return html, wrap_css(css_obj, is_file=is_file, class_wrapper=class_wrapper)[0]
                return html, css_obj

            if cssfile:
                new_cssfile = cssfile if cssfile.startswith('_') else u'_' + cssfile
                css_path = cls.media_path(new_cssfile)
                copy_static_file(cssfile, css_path)
                res, new_cssfile = wrap(res, css_path)
                new_cssfile = os.path.basename(new_cssfile)
                res = u'<link type="text/css" rel="stylesheet" href="{0}" />{1}'.format(new_cssfile, res)
            if css:
                res, css = wrap(res, css, is_file=False)
                res = u'<style>{0}</style>{1}'.format(css, res)

            if not isinstance(res, QueryResult):
                return QueryResult(result=res, jsfile=jsfile, js=js)
            else:
                res.set_styles(jsfile=jsfile, js=js)
                return res
        return _deco
    return _with

_BS_LOCKS = [_threading.Lock(), _threading.Lock()]

def parse_html(html):
    lock = random.choice(_BS_LOCKS)
    lock.acquire()
    soup = BeautifulSoup(html, 'html.parser')
    lock.release()
    return soup

def service_wrap(service, *args, **kwargs):
    def _service():
        return service(*args, **kwargs)
    _service.__service_class__ = service
    fields = {}
    for name, method in inspect.getmembers(service, predicate=_is_method_or_func):
        attrs = getattr(method, '__export_attrs__', None)
        if attrs:
            index = getattr(service, '__export_indexes__', {}).get(name, attrs[1])
            fields[int(index)] = attrs[0]
    _service.__fields__ = tuple(fields[index] for index in sorted(fields))
    return _service
