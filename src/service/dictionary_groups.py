"""One management row per local dictionary, retaining all legacy service IDs."""
import os
from pathlib import Path


def grouped_sources(registry, choices):
    custom = {item.__unique__ for item in registry.local_custom_services}
    groups = {}
    for factory in registry.local_services:
        path = getattr(factory, '__dict_path__', '')
        binding = getattr(factory, '__binding__', None)
        key = ('binding:' + repr(sorted(binding.items()))) if binding and binding.get('title') else (
            os.path.normcase(os.path.realpath(path)) if path else 'service:' + factory.__unique__)
        group = groups.setdefault(key, {'members': [], 'dict_path': path})
        if factory.__unique__ not in {item.__unique__ for item in group['members']}:
            group['members'].append(factory)
    result = []
    for group in groups.values():
        scripts = [item for item in group['members'] if item.__unique__ in custom]
        def priority(item):
            path = getattr(item, '__path__', '')
            return (bool(choices.get(item.__unique__, {}).get('enabled')), os.path.getmtime(path) if path and os.path.isfile(path) else 0)
        scripts.sort(key=priority, reverse=True)
        primary = (scripts or group['members'])[0]
        binding = getattr(primary, '__binding__', {})
        group.update(primary=primary, scripts=scripts,
                     script_paths=list(dict.fromkeys(getattr(item, '__path__', '') for item in scripts if getattr(item, '__path__', ''))),
                     uniques=[item.__unique__ for item in group['members']],
                     title=binding.get('file') or (Path(group['dict_path']).stem if group['dict_path'] else primary.__title__),
                     dictionary_title=binding.get('title', ''), binding_status=getattr(primary, '__binding_status__', ''))
        result.append(group)
    return result
