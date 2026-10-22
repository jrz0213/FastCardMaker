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

import ssl
import sys

from anki.hooks import addHook
from anki.utils import is_mac

sys.dont_write_bytecode = True
if is_mac:
    ssl._create_default_https_context = ssl._create_unverified_context

############## other config here ##################
shortcut = ('Ctrl+Alt' if is_mac else 'Ctrl') + '+Q'

###################################################


def start_here():
    from .context import config
    config.activate_profile()
    from .service.ai_support.migration import migrate_plaintext
    migrate_plaintext()
    from . import common as fastcm
    from .utils.logger import set_logging_state  # 引入底层日志控制接口
    
    from .service import service_manager, service_pool
    from .service.ai_config import clear_session_keys
    clear_session_keys()
    service_pool.clean()
    from .service.refresh import get_updater
    get_updater().request()
    from .query.automatic import configure_automatic
    configure_automatic()
    from .gui.result_recovery import notify_recovery
    notify_recovery()
    
    # 🌟 日志系统热启动：在配置加载后，强制同步一次本地保存的日志状态
    saved_state = getattr(config, 'enable_logging', False)
    set_logging_state(saved_state)
    
    fastcm.my_shortcut = shortcut
    if not fastcm.have_setup:
        fastcm.have_setup = True
        fastcm.config_menu()
        fastcm.browser_menu()
        fastcm.context_menu()
        fastcm.customize_addcards()

addHook("profileLoaded", start_here)


def _close_profile():
    from .gui.type_query import close_type_queries
    close_type_queries()
    from aqt import mw
    recovery = getattr(mw, '_fwq_recovery_dialog', None)
    if recovery is not None:
        recovery.close()
    from .query.automatic import get_scheduler
    get_scheduler().stop()
    from .query.session import cancel_active_sessions
    from .service import service_pool
    from .service.ai_config import clear_session_keys
    cancel_active_sessions(wait=True)
    from .gui.task_progress import progress_hub
    progress_hub().clear()
    from .service.refresh import get_updater
    from .gui.service_loader import cancel_loaders
    get_updater().cancel(wait=True)
    cancel_loaders(wait=True)
    service_pool.clean()
    clear_session_keys()


from aqt import gui_hooks
gui_hooks.profile_will_close.append(_close_profile)
def _automatic_settings_changed():
    from .query.automatic import configure_automatic
    configure_automatic()

addHook('config.update', _automatic_settings_changed)
