import inspect
import os
import importlib
import traceback  # 【新增】：用于提取详细的错误堆栈信息
import sys
import re
import types
from pathlib import Path
from threading import RLock
from hashlib import md5

from .base import LocalService, MdxService, StardictService, WebService, service_wrap
from ..context import config
# 引入全局日志对象
from ..utils.logger import logger

_SCAN_LOCK = RLock()


class ServiceManager(object):
    """
    Query service class manager
    """

    def __init__(self, auto_update=True, settings=None, cancelled=None):
        self._settings = settings
        self._cancelled = cancelled
        self._registry_lock = RLock()
        self.revision = 0
        self.web_services = []
        self.local_services = []
        self.local_custom_services = []
        self.mdx_services = []
        self.star_dict_services = []
        if auto_update:
            self.update_services()

    @property
    def settings(self):
        return getattr(self, '_settings', None) or config

    def _check_cancelled(self):
        cancelled = getattr(self, '_cancelled', None)
        if cancelled and cancelled():
            raise ScanCancelled()

    def adopt(self, prepared):
        with self._registry_lock:
            for name in ('web_services', 'local_services', 'local_custom_services', 'mdx_services',
                         'star_dict_services', 'loaded_scripts', 'supported_custom_paths', 'custom_sources'):
                setattr(self, name, getattr(prepared, name))
            self.aliases = getattr(prepared, 'aliases', {})
            self.catalogue = getattr(prepared, 'catalogue', None)
            self.revision += 1

    @property
    def services(self):
        lock = getattr(self, '_registry_lock', None)
        if lock is None:
            return self.web_services + self.local_services
        with lock:
            return self.web_services + self.local_services

    def update_services(self):
        from .dictionary_binding import Catalogue, use_catalogue
        self.catalogue = Catalogue(getattr(self.settings, 'dirs', []), getattr(self, '_cancelled', None))
        self.aliases = {}
        with _SCAN_LOCK, use_catalogue(self.catalogue):
            self._update_services()

    def _update_services(self):
        self._check_cancelled()
        from .script_updates import prune_old_scripts
        try:
            from .script_library import script_directory
            prune_old_scripts(script_directory())
        except (OSError, ValueError):
            logger.exception('Could not expire recycled dictionary scripts')
        logger.info("开始更新并重新扫描所有词典服务...")
        
        # ===================================================
        # 🌟 核心修改：扫描外部目录，若发现同名 .py，则自动复制并覆盖内部
        # ===================================================
        prefix = __package__ + '.dict'
        for name in list(sys.modules):
            if name == prefix or name.startswith(prefix + '.'):
                del sys.modules[name]
        importlib.invalidate_caches()
        
        # 优先扫描并加载自定义脚本服务，获取成功加载的脚本名称列表
        self.web_services, self.local_custom_services, self.loaded_scripts = self._get_services_from_files()
        
        # 将成功加载的脚本列表传入，以便在扫描本地词典时提供 Fallback 降级机制
        self.mdx_services, self.star_dict_services = self._get_available_local_services(self.loaded_scripts)
        
        # combine the customized local services into local services
        self.local_services = self.mdx_services + self.star_dict_services + self.local_custom_services
        
        logger.info(f"服务更新完成 | 共加载: 网络词典 {len(self.web_services)} 个, 本地词典 {len(self.local_services)} 个 (含自定义 {len(self.local_custom_services)} 个)")

    def is_enabled(self, unique):
        return bool(self.settings.dicts.get(unique, {}).get('enabled', False))

    def get_service(self, unique):
        unique = getattr(self, 'aliases', {}).get(unique, unique)
        if not self.is_enabled(unique):
            return None
        # webservice unique: class name
        # mdxservice unique: md5 of dict filepath
        for each in self.services:
            if each.__unique__ == unique:
                try:
                    # 尝试实例化该词典服务（无论是默认的还是自定义的脚本）
                    service = each()
                    service.unique = unique
                    return service
                except Exception as e:
                    import traceback
                    error_details = traceback.format_exc()
                    logger.error(f"[服务调度] 初始化词典服务失败，请检查脚本或重新选择词典 | Unique: [{unique}] | 错误信息: {str(e)}\n【详细错误堆栈】:\n{error_details}")
                    # 返回 None，GUI 层（options.py）判断为 None 就会自动跳过，不再引发崩溃
                    return None

    def _get_services_from_files(self, *args):
        """
        get service from service packages, available type is
        WebService, LocalService
        """
        service_path = u'dict'
        from .dictionary_binding import Catalogue
        if not hasattr(self, 'catalogue'):
            self.catalogue = Catalogue(self.settings.dirs)
        web_services, local_custom_services = list(), list()
        loaded_scripts = set()
        supported_paths = set()
        custom_sources = {}
        mypath = os.path.join(os.path.dirname(os.path.realpath(__file__)), service_path)
        
        logger.info(f"扫描自定义词典脚本目录: [{mypath}]")
        
        files = [
            f for f in os.listdir(mypath) \
            if f not in ('__init__.py') and \
            f.endswith('.py') and \
            not os.path.isdir(mypath+os.sep+f)
        ]
        library = getattr(self.settings, 'script_library', None)
        if library is None:
            data = getattr(self.settings, 'data', {})
            library = data.get('script_library', {}) if isinstance(data, dict) else {}
        from .script_library import validate
        validate(library)
        files = sorted(set(files) | set(library))
        from .script_library import script_directory
        cache = script_directory()
        cache.mkdir(parents=True, exist_ok=True)
        files = sorted(set(files) | {path.name for path in cache.glob('*.py')})
        from ..utils.config_storage import read_object
        excluded = set(read_object(cache / '.sync-state.json').get('excluded', []))
        files = [name for name in files if name not in excluded]
        self.script_library = {}
        base_class = (
            WebService, 
            LocalService,
            MdxService, 
            StardictService
        )
        
        for f in files:
            self._check_cancelled()
            try:
                from .dictionary_binding import portable_source, source_binding, resolve_dictionary
                cached = cache / f
                if cached.is_file():
                    source = portable_source(cached.read_text(encoding='utf-8'))
                elif f in library:
                    source = library[f]['source']
                else:
                    import tokenize
                    original_path = os.path.join(mypath, f)
                    if os.path.isfile(original_path):
                        with tokenize.open(original_path) as stream:
                            source = portable_source(stream.read())
                    else:
                        source = ''
                binding = source_binding(source)
                if binding and not binding.get('title'):
                    from .dictionary_binding import descriptor
                    candidates = getattr(self, 'catalogue', None)
                    candidates = candidates.files.get(binding['file'].casefold(), []) if candidates else []
                    if len(candidates) == 1 and descriptor(candidates[0])['title']:
                        source = portable_source(source, candidates[0])
                # Load profile-specific source without rewriting the shipped scripts.
                name = __package__ + '.dict.' + os.path.splitext(f)[0]
                module = types.ModuleType(name) if source else importlib.import_module('.dict.' + os.path.splitext(f)[0], __package__)
                module.__package__ = __package__ + '.dict'
                module.__file__ = str(cached)
                sys.modules[name] = module
                exec(compile(source, module.__file__, 'exec'), module.__dict__)
                if not cached.exists() or cached.read_text(encoding='utf-8') != source:
                    cached.write_text(source, encoding='utf-8')
                self.script_library[f] = {'source': source}
                binding = source_binding(source)
                
                has_valid_service = False
                
                for name, clazz in inspect.getmembers(module, predicate=inspect.isclass):
                    self._check_cancelled()
                    if clazz in base_class or clazz.__module__ != module.__name__:
                        continue
                    if not(issubclass(clazz, WebService) or issubclass(clazz, LocalService)):
                        continue
                    if getattr(clazz, '__register_label__', None) is None:
                        continue
                        
                    service = service_wrap(clazz, *args)
                    service.__title__ = getattr(clazz, '__register_label__', name)
                    service.__unique__ = name
                    service.__path__ = str(cached)
                    service.__source__ = source
                    if binding:
                        service.__binding__ = binding
                        clazz.__dict_binding__ = binding
                        service.__dict_path__ = resolve_dictionary(binding['file'], binding['title'])
                        if not os.path.isfile(service.__dict_path__):
                            service.__binding_status__ = ('ambiguous' if len(self.catalogue.candidates(binding)) > 1 else 'missing')
                    declared_path = getattr(module, 'DICT_PATH', '')
                    if isinstance(declared_path, str) and not binding:
                        service.__dict_path__ = declared_path
                    
                    if issubclass(clazz, WebService):
                        web_services.append(service)
                        logger.info(f"成功加载网络词典/服务: [{service.__title__}] -> 文件: {f}")
                        has_valid_service = True
                        
                    # get the customized local services
                    if issubclass(clazz, LocalService):
                        local_custom_services.append(service)
                        try:
                            instance = service()
                            path = getattr(instance, 'dict_path', '')
                            if isinstance(path, str) and path:
                                service.__dict_path__ = path
                                if not binding and os.path.isfile(path):
                                    from .dictionary_binding import descriptor
                                    discovered = descriptor(path)
                                    if discovered['title']:
                                        source = portable_source(source, path)
                                        cached.write_text(source, encoding='utf-8')
                                        service.__binding__ = clazz.__dict_binding__ = discovered
                                        service.__source__ = source
                            if instance.support and path and MdxService.check(path):
                                if not getattr(clazz, '__keep_default_mdx__', False):
                                    supported_paths.add(os.path.normcase(os.path.realpath(path)))
                                    custom_sources[os.path.normcase(os.path.realpath(path))] = service.__unique__
                                service.__dict_path__ = path
                        except Exception:
                            logger.exception('Custom dictionary is unavailable; retaining default MDX fallback: %s', f)
                        has_valid_service = True

                # 如果脚本内有合法的服务类注册，则记录为成功加载的脚本
                if has_valid_service:
                    loaded_scripts.add(f)
                        
            except ScanCancelled:
                raise
            except Exception as e:
                # 【修改】：使用 traceback 获取完整的报错行号和错误类型，方便排查脚本 bug
                error_details = traceback.format_exc()
                logger.error(f"加载自定义词典脚本失败: [{f}] | 错误信息: {str(e)}\n【详细错误堆栈】:\n{error_details}")
                
        web_services = sorted(web_services, key=lambda service: service.__title__)
        local_custom_services = sorted(local_custom_services, key=lambda service: service.__title__)
        
        self.supported_custom_paths = supported_paths
        self.custom_sources = custom_sources
        return web_services, local_custom_services, loaded_scripts

    def _get_available_local_services(self, loaded_scripts):
        '''
        available local dictionary services
        '''
        mdx_services = list()
        from .dictionary_binding import Catalogue
        if not hasattr(self, 'catalogue'):
            self.catalogue = Catalogue(self.settings.dirs)
        if not hasattr(self, 'aliases'):
            self.aliases = {}
        star_dict_services = list()
        logger.info("扫描本地词典目录 (配置的文件夹)...")
        
        for each in self.settings.dirs:
            self._check_cancelled()
            for dirpath, dirnames, filenames in os.walk(each):
                for filename in filenames:
                    self._check_cancelled()
                    try:
                        service = None
                        dict_path = os.path.join(dirpath, filename)
                        
                        # MDX
                        if MdxService.check(dict_path):
                            from .dictionary_binding import descriptor, identity
                            binding = descriptor(dict_path)
                            canonical_path = os.path.normcase(os.path.realpath(dict_path))
                            custom_unique = getattr(self, 'custom_sources', {}).get(canonical_path)
                            if (canonical_path in getattr(self, 'supported_custom_paths', set()) and
                                    self.settings.dicts.get(custom_unique, {}).get('enabled', False)):
                                continue

                            service = service_wrap(MdxService, dict_path)
                            service.__dict_path__ = dict_path
                            service.__binding__ = binding
                            service.__title__ = os.path.splitext(filename)[0]
                            legacy = md5(str(dict_path).encode('utf-8')).hexdigest()
                            service.__unique__ = 'mdx_' + identity(binding)
                            self.aliases[legacy] = service.__unique__
                            for old, saved in getattr(self.settings, 'dictionary_bindings', {}).items():
                                if saved == binding:
                                    self.aliases[old] = service.__unique__
                            if not binding['title']:
                                # Invalid/untitled headers cannot be auto-matched across machines.
                                service.__unique__ = legacy
                                self.aliases[legacy] = legacy
                            elif len(self.catalogue.candidates(binding)) > 1:
                                service.__binding_status__ = 'ambiguous'
                                from .dictionary_binding import resolve_dictionary
                                missing = resolve_dictionary(binding['file'], binding['title'])
                                unavailable = service_wrap(MdxService, missing)
                                unavailable.__dict__.update(service.__dict__)
                                unavailable.__dict_path__ = missing
                                service = unavailable
                            if any(item.__unique__ == service.__unique__ for item in mdx_services):
                                continue
                            mdx_services.append(service)
                            logger.info(f"成功发现本地 MDX 词典: [{filename}]")
                            
                        # Stardict    
                        elif StardictService.check(dict_path):
                            service = service_wrap(StardictService, dict_path)
                            service.__dict_path__ = dict_path
                            service.__title__ = os.path.splitext(filename)[0]
                            service.__unique__ = md5(str(dict_path[:-4]).encode('utf-8')).hexdigest()
                            star_dict_services.append(service)
                            logger.info(f"成功发现本地 Stardict 词典: [{filename}]")
                            
                    except Exception as e:
                        # 【修改】：增加防崩溃保护和详细日志，防止某个损坏的文件中断整个扫描过程
                        error_details = traceback.format_exc()
                        logger.error(f"解析本地词典文件异常: [{filename}] | 错误信息: {str(e)}\n【详细错误堆栈】:\n{error_details}")
                        
        return mdx_services, star_dict_services


class ScanCancelled(Exception):
    pass
    
    
# ==========================================
# 🌟 新增：全局静默预热机制 (启动后3秒自动建库)
# ==========================================
from aqt import gui_hooks
from aqt.qt import QTimer

def _auto_prewarm_dictionaries():
    logger.info("[全局预热] 检测本地词典索引状态...")
    try:
        # 预先扫描所有词典文件路径
        from . import service_manager as mgr
        
        # 遍历本地词典，预先实例化它们以触发 base.py 中的 _get_builder 
        # 从而把任务全部送进 _DictBuilderQueueThread 后台线程
        count = 0
        for svc_wrap in mgr.local_services:
            try:
                svc_wrap()  # 触发 MdxService/StardictService 的 __init__
                count += 1
            except Exception:
                pass
                
        logger.info(f"[全局预热] 分发完成！共触发 {count} 个本地词典的后台状态检测。")
    except Exception as e:
        logger.error(f"[全局预热] 异常: {str(e)}")

def _on_profile_loaded():
    # 延迟 10000 毫秒后执行静默预热，避开 Anki 刚启动时的卡顿高峰
    from ..utils.media import profile_token
    token = profile_token()
    QTimer.singleShot(10000, lambda: _auto_prewarm_dictionaries() if token == profile_token() else None)

# 将预热函数挂载到 Anki 的“配置打开完成”钩子上
gui_hooks.profile_did_open.append(_on_profile_loaded)
