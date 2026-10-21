

import io
import os
import re
import shutil
import unicodedata
from collections import defaultdict

from aqt.qt import *
from aqt.utils import showInfo

from ..constants import Template
from ..context import config
from ..libs.snowballstemmer import stemmer
from ..service import QueryResult, copy_static_file, service_pool
from ..service.base import LocalService
from ..utils import wrap_css
from ..lang import _
from ..translations import text as tr
# 引入全局日志对象
from ..utils.logger import logger
from ..service.ai_config import is_ai
from ..service.ai import query_ai
from ..service.ai_validation import validate_ai_references

__all__ = [
    'InvalidWordException', 'update_note_fields', 'update_note_field',
    'promot_choose_css', 'add_to_tmpl', 'query_flds', 'inspect_note'
]


class InvalidWordException(Exception):
    """Invalid word exception"""


def inspect_note(note, mappings=None):
    """
    inspect the note, and get necessary input parameters
    return word_ord: field index of the word in current note
    return word: the word
    return maps: dicts map of current note
    """

    if mappings is None:
        mappings = getattr(note, '_query_mappings', None)
    if mappings is None:
        conf = config.get_maps(note.note_type()['id'])
        maps_list = {'list': [conf], 'def': 0} if isinstance(conf, list) else conf
        maps = maps_list['list'][maps_list['def']]
        maps = maps if isinstance(maps, list) else maps['fields']
    else:
        maps = mappings
    for i, m in enumerate(maps):
        if m.get('word_checked', False):
            word_ord = i
            break
    else:
        # if no field is checked to be the word field, default the
        # first one.
        word_ord = 0

    def purify_word(word):
        return word.strip() if word else ''

    source_name = maps[word_ord].get('fld_name') if maps and 0 <= word_ord < len(maps) else None
    positions = [field['name'] for field in note.note_type()['flds']]
    if source_name and source_name not in positions:
        logger.warning('Unavailable source field skipped: %s', source_name)
        return word_ord, '', maps
    source_position = positions.index(source_name) if source_name else word_ord
    word = purify_word(note.fields[source_position]) if 0 <= source_position < len(note.fields) else ''
    return word_ord, word, maps


def strip_combining(txt):
    """Return txt with all combining characters removed."""
    norm = unicodedata.normalize('NFKD', txt)
    return u"".join([c for c in norm if not unicodedata.combining(c)])


def update_note_fields(note, results, settings=None):
    """
    Update query result to note fields, return updated fields count.
    """

    if not results or not note or len(results) == 0:
        return 0
    count = 0
    for i, q in results.items():
        if isinstance(q, QueryResult) and i < len(note.fields):
            count += update_note_field(note, i, q, settings)

    return count


def update_note_field(note, fld_index, fld_result, settings=None):
    """
    Update single field, if result is valid then return 1, else return 0
    """

    result, js, jsfile = fld_result.result, fld_result.js, fld_result.jsfile
    # js process: add to template of the note model
    add_to_tmpl(note, js=js, jsfile=jsfile)
    # if not result:
    #     return
    if not (settings or config).force_update and not result:
        return 0

    value = result if result else ''
    if note.fields[fld_index] != value:
        note.fields[fld_index] = value
        return 1

    return 0


def promot_choose_css(missed_css):
    """
    Choose missed css file and copy to user folder
    """
    checked = set()
    for css in missed_css:
        from ..utils.media import media_path
        filename = media_path(css.get('destination', u'_' + css['file']), css.get('media_dir'))
        if not os.path.exists(filename) and not css['file'] in checked:
            checked.add(css['file'])
            showInfo(
                Template.miss_css.format(dict=css['title'], css=css['file']))
            try:
                filepath = css['dict_path'][:css['dict_path'].rindex(os.path.
                                                                     sep) + 1]
                # 修复 Qt6 返回元组的 Bug，使用 _, 忽略第二个返回值
                filepath, _ = QFileDialog.getOpenFileName(
                    directory=filepath,
                    caption=u'Choose css file',
                    filter=u'CSS (*.css)')
                if filepath:
                    shutil.copy(filepath, filename)
                    wrap_css(filename)

            except KeyError:
                pass


def add_to_tmpl(note, **kwargs):
    # templates
    """
    [{u'name': u'Card 1', u'qfmt': u'{{Front}}\n\n', u'did': None, u'bafmt': u'',
        u'afmt': u'{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}\n\n{{12}}\n\n{{44}}\n\n', u'ord': 0, u'bqfmt': u''}]
    """
    # showInfo(str(kwargs))
    afmt = note.note_type()['tmpls'][0]['afmt']
    if kwargs:
        jsfile, js = kwargs.get('jsfile', None), kwargs.get('js', None)
        if js and js.strip():
            addings = js.strip()
            if addings not in afmt:
                if not addings.startswith(u'<script') and not addings.endswith(
                        u'/script>'):
                    addings = u'\n<script type="text/javascript">\n{}\n</script>'.format(
                        addings)
                afmt += addings
        if jsfile:
            # new_jsfile = u'_' + \
            #     jsfile if not jsfile.startswith(u'_') else jsfile
            # copy_static_file(jsfile, new_jsfile)
            # addings = u'\r\n<script src="{}"></script>'.format(new_jsfile)
            # afmt += addings
            jsfile = jsfile if isinstance(jsfile, list) else [jsfile]
            for fn in jsfile:
                addings = '''
<script type="text/javascript">
    var script = document.createElement("script");
    script.src   = "{}";
    document.getElementsByTagName('head')[0].appendChild(script);
</script>'''.format(fn)
                if addings not in afmt:
                    afmt += addings
        note.note_type()['tmpls'][0]['afmt'] = afmt


def query_flds(note, fileds=None, cancelled=None, include_ai=True, mappings=None):
    """
    Query fields of single note
    """

    word_ord, word, maps = inspect_note(note, mappings)
    has_ai = include_ai and any(is_ai(item.get('dict_unique')) and not item.get('ignore', False)
                 for item in maps)
    if not word and not has_ai:
        raise InvalidWordException

    settings = getattr(note, '_query_settings', None) or config
    if settings.ignore_accents:
        word = strip_combining(word)

    # progress.update_title(u'Querying [[ %s ]]' % word)

    groups = {}
    ai_tasks = []
    field_values = dict(zip((field['name'] for field in note.note_type()['flds']), note.fields))
    for index, each in enumerate(maps):
        target = each.get('fld_ord', index)
        if each.get('fld_name'):
            names = [field['name'] for field in note.note_type()['flds']]
            if each['fld_name'] not in names:
                logger.warning('Unavailable target field skipped: %s', each['fld_name'])
                continue
            target = names.index(each['fld_name'])
        if index == word_ord or not 0 <= target < len(note.fields) or each.get('ignore', False):
            continue
        if fileds is not None and target not in fileds:
            continue
        if each.get('skip_valued', False) and note.fields[target]:
            continue
        unique = str(each.get('dict_unique') or '').strip()
        if is_ai(unique):
            if include_ai:
                ai_tasks.append((target, each))
        elif word and unique and each.get('dict_fld_ord', -1) != -1:
            groups.setdefault(unique, []).append((target, each))

    success_num = 0
    result = FieldResults()
    missed_css = []

    def stopped():
        return bool(cancelled and cancelled())

    def collect(target, mapping, qr):
        nonlocal success_num
        if qr and not stopped():
            qr = QueryResult(qr)  # Do not mutate a service's cached result.
            if mapping.get('cloze_word') and word:
                qr['result'] = cloze_deletion(qr['result'], word, settings)
            result[target] = qr
            success_num += 1

    for unique, tasks in groups.items():
        if stopped():
            break
        service = None
        try:
            service = service_pool.get(unique, cancelled=stopped)
            if service is None or not service.support:
                if not stopped():
                    raise ValueError(tr('词典不可用或等待超时，请检查词典路径和脚本。'))
                break
            for target, mapping in tasks:
                if stopped():
                    break
                try:
                    field_order = mapping['dict_fld_ord']
                    fields = getattr(service, 'fields', None)
                    if (mapping.get('dict_fld_name') and isinstance(fields, (list, tuple)) and
                            (not 0 <= field_order < len(fields) or fields[field_order] != mapping['dict_fld_name'])):
                        logger.warning('Unavailable dictionary item skipped: %s', mapping['dict_fld_name'])
                        continue
                    if (type(field_order) is not int or field_order < 0 or
                            isinstance(fields, (list, tuple)) and field_order >= len(fields)):
                        raise ValueError(tr('词典字段不可用，请手动选择有效字段。'))
                    collect(target, mapping, service.active(field_order, word))
                except Exception as error:
                    result.errors.append(str(error))
                    logger.warning('Dictionary field failed: %s', error)
            if isinstance(service, LocalService):
                missed_css.extend({'dict_path': service.dict_path, 'title': service.title, 'file': css,
                                   'media_dir': service.media_dir,
                                   'destination': service.media_name(css) if hasattr(service, 'media_name') else '_' + css}
                                  for css in service.missed_css)
        except Exception as error:
            result.errors.append(str(error))
            logger.warning('Dictionary unavailable: %s', error)
        finally:
            service_pool.put(service)

    for target, mapping in ai_tasks:
        if stopped():
            break
        try:
            validate_ai_references(mapping.get('ai_prompt', ''), maps, list(field_values))
            collect(target, mapping, query_ai(mapping['dict_unique'], mapping.get('ai_prompt', ''),
                                              field_values, cancelled=cancelled))
        except Exception as error:
            logger.warning('AI field failed: %s', error)

    return result, -1 if not groups and not ai_tasks else success_num, missed_css


class FieldResults(defaultdict):
    def __init__(self):
        super().__init__(QueryResult)
        self.errors = []


def cloze_deletion(text, cloze, settings=None):
    from ..utils.cloze import cloze_html
    return cloze_html(text, cloze, _stemmer, (settings or config).cloze_str)


_stemmer = stemmer('english')
