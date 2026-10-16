"""Adapt and copy external dictionary scripts into the plugin."""

import os
import re

from ..utils.logger import logger


def process_and_copy_custom_py(mdx_path, py_path, dict_folder_path, enable=True):
    """
    处理并拷贝自定义 .py 文件到 dict 目录
    """
    if not os.path.exists(dict_folder_path):
        os.makedirs(dict_folder_path, exist_ok=True)

    dict_name = os.path.splitext(os.path.basename(mdx_path))[0]
    safe_title = dict_name.replace('[', '_').replace(']', '_')
    safe_title_escaped = safe_title.replace("'", "\\'")

    with open(py_path, 'r', encoding='utf-8') as f:
        content = f.read()

    from .dictionary_binding import portable_source
    content = portable_source(content, mdx_path)

    def sanitize_register(match):
        text = match.group(0)
        def replace_brackets(m_str):
            return m_str.group(0).replace('[', '_').replace(']', '_')
        return re.sub(r"[uU]?[rR]?['\"].*?['\"]", replace_brackets, text)

    content = re.sub(r"@register\(\s*\[.*?\]\s*\)", sanitize_register, content)

    def inject_name(match):
        text = match.group(0)
        quotes_content = re.findall(r"['\"](.*?)['\"]", text)
        if quotes_content and all(not val.strip() for val in quotes_content):
            return f"@register([u' -{safe_title_escaped}', u'MDX-{safe_title_escaped}'])"
        return text

    content = re.sub(r"@register\(\s*\[.*?\]\s*\)", inject_name, content)

    content = re.sub(
        r"from\s+[A-Za-z0-9_.]*?service\.base\s+import",
        "from ..base import",
        content
    )

    dest_py_path = os.path.join(dict_folder_path, os.path.basename(py_path))
    with open(dest_py_path, 'w', encoding='utf-8') as f:
        f.write(content)

    from ..context import config
    match = re.search(r"class\s+([A-Za-z0-9_]+)\s*\(", content)
    if match and enable:
        unique_key = match.group(1)
        dicts_conf = config.dicts
        if unique_key not in dicts_conf:
            dicts_conf[unique_key] = {}
        dicts_conf[unique_key]['enabled'] = True
        config.update({'dicts': dicts_conf})
    logger.info(f"脚本自动同步成功 | 词典: [{dict_name}] | 目标文件: [{os.path.basename(dest_py_path)}]")
    return match.group(1) if match else None
