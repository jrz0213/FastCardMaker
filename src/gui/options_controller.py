# -*- coding:utf-8 -*-
import concurrent.futures
from copy import deepcopy
from threading import Lock
from ..utils.media import profile_token
from ..service.web import WebService
from ..context import config
from ..service import service_manager, service_pool
from ..service.base import LocalService
from ..utils.logger import logger
from aqt import mw
from aqt.qt import QApplication, QMessageBox  # 新增引入 Qt 组件
from aqt.utils import showWarning
from .progress import ProgressWindow
from ..service.ai_config import profile_choices, is_ai
from ..translations import text as tr

_CACHE = {}
_CACHE_LOCK = Lock()


def static_web_metadata(factory):
    cls = getattr(factory, '__service_class__', None)
    if (isinstance(cls, type) and issubclass(cls, WebService) and
            cls.fields is WebService.fields and cls.support is WebService.support and cls.title is WebService.title and
            cls._get_exporters is WebService._get_exporters):
        return {'title': factory.__title__, 'unique': factory.__unique__, 'fields': factory.__fields__}
    return None


class OptionsController:
    """
    选项面板的控制器 (Controller)
    """
    def __init__(self):
        self.dict_services = {'local': [], 'web': [], 'ai': []}

    def get_last_model_id(self):
        return config.last_model_id

    def get_maps(self, model_id):
        return config.get_maps(model_id)

    def _cache_key(self):
        return (profile_token(), getattr(service_manager, 'revision', 0),
                tuple(sorted((key, bool(value.get('enabled', False))) for key, value in config.dicts.items())),
                config.use_filename)

    def has_cached_services(self):
        with _CACHE_LOCK:
            return self._cache_key() in _CACHE

    def preview_services(self):
        key = self._cache_key()
        with _CACHE_LOCK:
            cached = deepcopy(_CACHE.get(key))
        if cached is None:
            cached = {'local': [], 'web': [], 'ai': []}
            for factory in list(service_manager.web_services):
                if config.dicts.get(factory.__unique__, {}).get('enabled', False):
                    metadata = static_web_metadata(factory)
                    if metadata:
                        cached['web'].append(metadata)
            cached['web'].sort(key=lambda item: item['title'])
        for service in cached['local']:
            if service.get('path'):
                service['status'] = LocalService.get_db_status(service['path'])
        cached['ai'] = profile_choices()
        self.dict_services = cached
        return cached

    def needs_background_load(self):
        enabled = config.dicts
        if any(enabled.get(factory.__unique__, {}).get('enabled', False)
               for factory in list(service_manager.local_services)):
            return True
        if self.has_cached_services():
            return False
        return any(enabled.get(factory.__unique__, {}).get('enabled', False) and
                   static_web_metadata(factory) is None for factory in list(service_manager.web_services))

    def load_services(self, cancelled=None, progress=None):
        key = self._cache_key()
        token = profile_token()
        enabled = deepcopy(config.dicts)
        services = {'local': [], 'web': [], 'ai': profile_choices()}
        local = [factory for factory in list(service_manager.local_services)
                 if enabled.get(factory.__unique__, {}).get('enabled', False)]
        web = [factory for factory in list(service_manager.web_services)
               if enabled.get(factory.__unique__, {}).get('enabled', False)]
        total = len(local) + len(web)
        done = 0

        def stopped():
            return (cancelled and cancelled()) or token != profile_token()

        def inspect_service(factory, is_local):
            if stopped():
                return None
            if not is_local:
                metadata = static_web_metadata(factory)
                if metadata:
                    return metadata
            service = None
            try:
                service = service_pool.get(factory.__unique__, timeout=1, cancelled=stopped)
                if service and service.support and not stopped():
                    metadata = {'title': service.title, 'unique': service.unique, 'fields': service.fields}
                    if is_local:
                        path = getattr(service, 'dict_path', None)
                        metadata.update(path=path, status=LocalService.get_db_status(path) if path else 'ready')
                    return metadata
            except Exception:
                logger.exception('Could not inspect dictionary')
            finally:
                service_pool.put(service)
            return None

        def collect(metadata, kind):
            nonlocal done
            if metadata:
                services[kind].append(metadata)
            done += 1
            if progress and not stopped():
                progress(done, total)

        for factory in local:
            if stopped():
                return services
            collect(inspect_service(factory, True), 'local')
        dynamic = []
        for factory in web:
            if stopped():
                return services
            metadata = static_web_metadata(factory)
            if metadata:
                collect(metadata, 'web')
            else:
                dynamic.append(factory)
        if dynamic:
            count = max(1, min(16, int(config.thread_number), len(dynamic)))
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=count)
            pending = {executor.submit(inspect_service, factory, False) for factory in dynamic}
            try:
                while pending:
                    if stopped():
                        for future in pending:
                            future.cancel()
                        break
                    finished, pending = concurrent.futures.wait(pending, timeout=0.05,
                                                               return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in finished:
                        collect(future.result(), 'web')
            finally:
                # Waiting happens in the loader, never while closing the dialog.
                executor.shutdown(wait=True, cancel_futures=True)
        if not stopped() and key == self._cache_key():
            for kind in ('local', 'web'):
                services[kind].sort(key=lambda item: item['title'])
            with _CACHE_LOCK:
                _CACHE.clear()
                _CACHE[key] = deepcopy(services)
        return services

    def check_dict_status(self):
        changed = False
        all_ready = True
        for service in self.dict_services.get('local', []):
            current = LocalService.get_db_status(service['path']) if service.get('path') else 'ready'
            if service.get('status') != current:
                service['status'] = current
                changed = True
            all_ready = all_ready and current == 'ready'
        return changed, all_ready

    def get_service_fields(self, unique_id):
        if is_ai(unique_id):
            return [tr('AI 回复')]
        for service in self.dict_services['local'] + self.dict_services['web']:
            if service['unique'] == unique_id and service.get('fields'):
                return service['fields']
        return []

    def save_config(self, current_model, tabs_data):
        if not current_model: return
        data = dict()
        current_model_id = str(current_model['id'])
        data[current_model_id] = tabs_data
        data['last_model'] = current_model['id']
        logger.info(f"保存查询选项配置 | 目标模型: [{current_model['name']}] | 包含标签页: {len(tabs_data['list'])} 个")
        config.update(data)

    def is_logging_enabled(self):
        from ..context import config
        return getattr(config, 'enable_logging', False)

    def toggle_logging(self):
        from ..context import config
        from ..utils.logger import set_logging_state
        
        current_state = self.is_logging_enabled()
        new_state = not current_state
        config.update({'enable_logging': new_state})
        set_logging_state(new_state)
        return new_state


    # =======================================================================
    # 一键批量查词引擎 
    # =======================================================================
    def execute_batch_query(self, model, config_data, parent_window=None):
        if not model or not config_data:
            return

        source_field = None
        targets = []
        for conf in config_data:
            if conf.get('word_checked', False):
                source_field = conf['fld_name']
            elif not conf.get('ignore', True):
                targets.append(conf)

        if not source_field:
            showWarning(tr('未指定单词提取来源。请在列表最左侧勾选一个目标字段。'), parent=parent_window)
            return
        if not targets:
            showWarning(tr('无查词任务。请至少分配一个有效词典到空闲字段。'), parent=parent_window)
            return

        query_string = f"mid:{model['id']}"
        nids = mw.col.find_notes(query_string)
        if not nids:
            showWarning(tr('未找到笔记类型“%s”的笔记。') % model['name'], parent=parent_window)
            return

        from ..query.background import start_query_session, active_job
        if active_job():
            active_job().show_progress()
            return
        notes = [mw.col.get_note(nid) for nid in nids]
        mappings = [dict(item) for item in config_data]
        positions = {field['name']: index for index, field in enumerate(model['flds'])}
        for item in mappings:
            item.setdefault('fld_ord', positions.get(item.get('fld_name'), 0))
        try:
            mw.checkpoint('FastCM batch query')
            return start_query_session(notes, mappings=mappings, model=model,
                writer=mw.col.update_note, parent=parent_window)
        except Exception as error:
            logger.error('Batch query interrupted: %s', type(error).__name__)
            showWarning(tr('执行时发生错误，请查看日志。'), parent=parent_window)
