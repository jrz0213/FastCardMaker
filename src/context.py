# -*- coding:utf-8 -*-
#
# Copyright (C) 2018 sthoo <sth201807@gmail.com>
#
# Support: Report an issue at https://github.com/sth2018/FastWordQuery/issues
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version; http://www.gnu.org/copyleft/gpl.html.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import json
import os
from pathlib import Path
from copy import deepcopy
from .utils.config_storage import portable, restore_portable, fingerprint, read_object, atomic_write, validate_settings

from anki.hooks import runHook
from aqt import mw

from .constants import VERSION
from .utils import get_icon

__all__ = ['APP_ICON', 'config']

APP_ICON = get_icon('wqicon.png')  # Addon Icon


class Config(object):
    """
    Addon Config
    """

    _CONFIG_FILENAME = 'fastcmcfg.json'

    def __init__(self, window):
        self.path = ''
        self.generation = 0
        self._profile_key = None
        self.window = window
        self.version = '0'
        self.data = None
        self._shared_hash = None
        self._sync_paused = False
        self.read()

    @property
    def pmname(self):
        return self.window.pm.name

    @property
    def media_dir(self):
        return os.path.join(self.window.pm.profileFolder(), 'collection.media')

    def activate_profile(self):
        self.read(force=True)
        # Compatibility for third-party scripts that still write relative paths.
        # Built-in media writers use an explicit captured media directory.
        os.makedirs(self.media_dir, exist_ok=True)
        os.chdir(self.media_dir)

    def update(self, data):
        self.read()
        updated = dict(self.data)
        updated.update({str(key): value for key, value in data.items()})
        updated['version'] = VERSION
        updated['%s_last' % self.pmname] = data.get('last_model', self.last_model_id)
        # An externally changed media file must never be overwritten by a save
        # from a window that was already open. Keep changes locally until chosen.
        try:
            shared = self.shared_settings()
        except (OSError, ValueError):
            shared = None
        expected_hash = fingerprint(shared) if shared is not None else None
        publish = not self._sync_paused and expected_hash is not None and expected_hash == self._local_shared_hash
        target_hash = fingerprint(updated) if publish else self._shared_hash
        self._write_local(updated, self._shared_hash)
        self.data = updated
        self._local_shared_hash = fingerprint(updated)
        if publish:
            try:
                latest = read_object(self.path)
                if fingerprint(latest) == expected_hash:
                    if latest != portable(updated):
                        atomic_write(self.path, portable(updated))
                    self._shared_hash = target_hash
                    self._write_local(updated, target_hash)
            except (OSError, ValueError):
                # The local save succeeded; keep a pending copy for resolution.
                self._sync_paused = True
        runHook('config.update')

    @property
    def local_path(self):
        return Path(self.window.pm.profileFolder()) / '_fastcm_local.json'

    def _write_local(self, data, shared_hash):
        atomic_write(self.local_path, {'format': 'fastcm-local', 'settings': data,
                                       'shared_hash': shared_hash})

    def shared_settings(self):
        return portable(validate_settings(read_object(self.path)))

    def settings_difference(self):
        remote, local = self.shared_settings(), portable(self.data)
        differences = sorted(key for key in set(remote) | set(local)
                             if key not in remote or key not in local or remote[key] != local[key])
        if not differences:
            self._shared_hash = fingerprint(remote)
            self._sync_paused = False
        return differences

    def resolve_settings(self, action):
        if action == 'cancel':
            self._sync_paused = True
            return
        if action not in ('overwrite', 'sync'):
            raise ValueError('Invalid configuration action')
        remote = self.shared_settings()
        updated = deepcopy(self.data) if action == 'overwrite' else restore_portable(remote, self.data)
        atomic_write(self.local_path.with_suffix('.previous.json'),
                     {'format': 'fastcm-local', 'settings': remote if action == 'overwrite' else self.data,
                      'shared_hash': self._shared_hash})
        if action == 'overwrite':
            atomic_write(self.path, portable(updated))
        self._shared_hash = fingerprint(updated)
        self._write_local(updated, self._shared_hash)
        self.data = updated
        self._local_shared_hash = fingerprint(updated)
        self._sync_paused = False
        runHook('config.update')

    def import_settings(self, settings):
        incoming = portable(validate_settings(settings, importing=True))
        updated = restore_portable(incoming, self.data)
        atomic_write(self.local_path.with_suffix('.previous.json'),
                     {'format': 'fastcm-local', 'settings': self.data, 'shared_hash': self._shared_hash})
        self._write_local(updated, self._shared_hash)
        self.data = updated
        self._local_shared_hash = fingerprint(updated)
        self._sync_paused = True
        runHook('config.update')

    def read(self, force=False):
        profile = os.path.normcase(os.path.abspath(self.window.pm.profileFolder()))
        changed = profile != self._profile_key
        if not force and not changed and self.data is not None:
            return self.data
        self.path = os.path.join(self.media_dir, '_' + self._CONFIG_FILENAME)
        candidates = [self.path, os.path.join(self.media_dir, '.' + self._CONFIG_FILENAME),
                      os.path.join(self.media_dir, '_fastwqcfg.json'),
                      os.path.join(self.media_dir, '.fastwqcfg.json')]
        path = next((candidate for candidate in candidates if os.path.exists(candidate)), self.path)
        local = read_object(self.local_path)
        try:
            if local:
                loaded = {}  # A bad remote file must not prevent local startup.
            else:
                with open(path, encoding='utf-8') as file:
                    loaded = json.load(file)
            if not isinstance(loaded, dict):
                raise ValueError('Invalid FastCard Maker configuration')
        except FileNotFoundError:
            loaded = {}
        if local:
            if local.get('format') != 'fastcm-local' or not isinstance(local.get('settings'), dict):
                raise ValueError('Invalid local FastCard Maker configuration')
            self.data = local['settings']
            self._shared_hash = local.get('shared_hash')
        else:
            self.data = loaded
            self._shared_hash = fingerprint(read_object(self.path))
        # Existing AI profiles are copied into portable settings in memory only.
        # Credentials continue to be read from the original local file until saved.
        if not local and 'ai_settings' not in self.data:
            account = Path(self.window.pm.profileFolder())
            for ai_path in (account / 'fastcm' / 'ai' / 'config.json',
                            Path(__file__).parent / 'service' / 'ai' / account.name / 'config.json'):
                if ai_path.exists():
                    self.data['ai_settings'] = portable(read_object(ai_path))
                    break
        self._local_shared_hash = fingerprint(self.data)
        self._sync_paused = False
        self._profile_key = profile
        self.generation += 1
        # Read older names, but keep them intact. The next explicit save writes
        # the new name atomically and it then takes precedence.
        return self.data

    def get_maps(self, model_id):
        """
        Query fileds map
        """
        return self.data.get(str(model_id), list())

    @property
    def last_model_id(self):
        return self.data.get('%s_last' % self.pmname, 0)

    @property
    def dirs(self):
        return self.data.get('dirs', list())

    @property
    def dicts(self):
        return self.data.get('dicts', dict())

    @property
    def ui_language(self):
        return self.data.get('ui_language', '')

    @property
    def auto_run(self):
        value = self.data.get('auto_run', {})
        return value if isinstance(value, dict) else {}

    @property
    def ai_send_mode(self):
        value = self.data.get('ai_send_mode', 'note')
        return value if value in ('field', 'note') else 'note'

    @property
    def ai_markdown(self):
        return self.data.get('ai_markdown', True)

    @property
    def ai_css_enabled(self):
        return self.data.get('ai_css_enabled', False)

    @property
    def ai_css(self):
        return self.data.get('ai_css')

    @property
    def ai_styles(self):
        value = self.data.get('ai_styles', {})
        return value if isinstance(value, dict) else {}

    @property
    def ai_profiles(self):
        return self.data.get('ai_profiles', [])

    @property
    def ai_settings(self):
        return self.data.get('ai_settings', {'profiles': self.ai_profiles})

    @property
    def ai_thread_number(self):
        return self.data.get('ai_thread_number', 4)

    @property
    def use_filename(self):
        return self.data.get('use_filename', True)

    @property
    def export_media(self):
        return self.data.get('export_media', False)

    @property
    def force_update(self):
        return self.data.get('force_update', False)

    @property
    def ignore_mdx_wordcase(self):
        return self.data.get('ignore_mdx_wordcase', False)

    @property
    def thread_number(self):
        """
        Query Thread Number
        """
        return self.data.get('thread_number', 16)

    @property
    def last_folder(self):
        """
        last file dialog open path
        """
        return self.data.get('last_folder', '')

    @property
    def ignore_accents(self):
        '''ignore accents of field in querying'''
        return self.data.get('ignore_accents', False)

    @property
    def cloze_str(self):
        '''cloze formater string'''
        tmpstr = self.data.get('cloze_str', '{{c1::%s}}')
        if len(tmpstr.split('%s')) != 2:
            tmpstr = '{{c1::%s}}'
        return tmpstr

    @property
    def sound_str(self):
        '''sound formater string'''
        # 设置音频播放按钮大小
        # <span style="width:24px;height:24px;">[sound:{0}]</span>
        tmpstr = self.data.get('sound_str', u'[sound:{0}]')
        if len(tmpstr.split('{0}')) != 2:
            tmpstr = u'[sound:{0}]'
        return tmpstr
    @property
    def fuzzy_match(self):
        """
        媒体资源全局模糊匹配开关
        """
        return self.data.get('fuzzy_match', True)

    @property
    def enable_logging(self):
        """
        全局日志系统开关
        """
        return self.data.get('enable_logging', False)

config = Config(mw)
