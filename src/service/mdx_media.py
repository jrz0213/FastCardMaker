"""Namespaced dictionary media, relative dependencies and HTML references."""

import os
import posixpath
import re
import sqlite3
import tempfile
import urllib.parse
from hashlib import sha1

from ..context import config
from ..utils import wrap_css
from ..utils.fuzzy_match import process_fuzzy_media
from ..utils.logger import logger
from .helpers import sanitize_to_safe_encoding


class MdxMediaMixin:
    RESOURCE_EXTENSIONS = {'.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',
                           '.bmp', '.ico', '.mp3', '.wav', '.ogg', '.aac', '.spx', '.m4a',
                           '.flac', '.mp4', '.webm', '.woff', '.woff2', '.ttf', '.otf'}

    @staticmethod
    def resource_key(resource):
        resource = urllib.parse.unquote(resource).replace('\\', '/')
        resource = urllib.parse.urlsplit(resource.lstrip('/')).path
        return posixpath.normpath(resource)

    def media_name(self, resource):
        resource = self.resource_key(resource)
        dictionary = os.path.normcase(os.path.realpath(self.dict_path))
        namespace = sha1(dictionary.encode('utf-8')).hexdigest()[:12]
        digest = sha1(resource.encode('utf-8')).hexdigest()[:16]
        base = sanitize_to_safe_encoding(posixpath.basename(resource))
        stem, extension = os.path.splitext(base)
        return '_fcm_%s_%s_%s%s' % (namespace, digest, stem[:64], extension)

    @staticmethod
    def _local_resource(resource):
        parsed = urllib.parse.urlsplit(resource)
        return bool(parsed.path) and not parsed.scheme and not parsed.netloc and not resource.startswith('#')

    def _read_resource(self, resource):
        key = self.resource_key(resource)
        source = os.path.abspath(os.path.join(os.path.dirname(self.dict_path), *key.split('/')))
        if os.path.isfile(source):
            with open(source, 'rb') as file:
                return file.read(), source
        mdd_key = '\\' + key.replace('/', '\\')
        ignorecase = config.ignore_mdx_wordcase
        values = self.builder.mdd_lookup(mdd_key, ignorecase=ignorecase)
        if isinstance(values, (list, tuple)) and values and isinstance(values[0], bytes):
            return values[0], None
        # A basename fallback is allowed only when it identifies a single entry.
        keys = self.builder.get_mdd_keys('*\\' + posixpath.basename(key))
        if len(keys) == 1:
            values = self.builder.mdd_lookup(keys[0], ignorecase=ignorecase)
            if isinstance(values, (list, tuple)) and values and isinstance(values[0], bytes):
                return values[0], None
        return None, None

    def _rewrite_dependencies(self, content, resource):
        directory = posixpath.dirname(self.resource_key(resource))
        def resolve(path):
            if not self._local_resource(path):
                return path
            parsed = urllib.parse.urlsplit(path)
            dependency = posixpath.normpath(posixpath.join(directory, urllib.parse.unquote(parsed.path)))
            saved = self.save_default_file(dependency)
            return (saved + ('#' + parsed.fragment if parsed.fragment else '')) if saved else path
        if resource.lower().endswith('.css'):
            def url(match):
                return 'url("' + resolve(match.group(2)) + '")'
            content = re.sub(r'url\(\s*([\'"]?)(.*?)\1\s*\)', url, content, flags=re.I)
            def imported(match):
                return '@import "' + resolve(match.group(2)) + '"'
            content = re.sub(r'@import\s+([\'"])(.*?)\1', imported, content, flags=re.I)
        elif resource.lower().endswith('.js'):
            def imported(match):
                path = match.group(3)
                if not path.startswith(('./', '../')):
                    return match.group(0)
                return match.group(1) + match.group(2) + './' + resolve(path) + match.group(2)
            content = re.sub(r'(\b(?:from|import)\s*|\bimport\s*\(\s*|\bnew\s+URL\s*\(\s*)([\'"])([^\'"\n]+)\2',
                             imported, content)
        return content

    def save_default_file(self, filepath_in_mdx, savepath=None):
        if not self._local_resource(filepath_in_mdx):
            return ''
        filename = savepath if savepath is not None else self.media_name(filepath_in_mdx)
        destination = self.media_path(filename)
        writing = getattr(self, '_media_writing', None)
        if writing is None:
            self._media_writing = writing = set()
        if destination in writing:
            return filename
        writing.add(destination)
        temporary = None
        try:
            payload, source = self._read_resource(filepath_in_mdx)
            if payload is None:
                return ''
            if filepath_in_mdx.lower().endswith(('.css', '.js')):
                payload = self._rewrite_dependencies(payload.decode('utf-8-sig', 'replace'), filepath_in_mdx).encode('utf-8')
            if os.path.exists(destination):
                with open(destination, 'rb') as file:
                    if file.read() == payload:
                        return filename
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=os.path.dirname(destination), prefix='.fcm-media-', delete=False) as file:
                temporary = file.name
                file.write(payload)
            os.replace(temporary, destination)
            return filename
        except (OSError, AttributeError, sqlite3.OperationalError) as error:
            logger.warning('Dictionary resource unavailable: %s', type(error).__name__)
            return ''
        finally:
            writing.discard(destination)
            if temporary and os.path.exists(temporary):
                os.remove(temporary)

    def save_media_files(self, data):
        saved = getattr(self, '_media_saved', None)
        if saved is None:
            self._media_saved = saved = {}
        errors = []
        for resource in data:
            filename = self.save_default_file(resource)
            if filename:
                saved[resource] = filename
            else:
                errors.append(resource)
        return errors

    def _is_fuzzy_enabled(self):
        return getattr(config, 'fuzzy_match', True)

    def adapt_to_anki(self, html):
        media_rules = getattr(self, '__media_rules__', None)
        if isinstance(media_rules, list) and media_rules:
            from .media_rules import repair_media
            html = repair_media(html, media_rules, self.builder, self.dict_path)
        attribute = re.compile(r"\b(src|href)\s*=\s*(['\"])(.*?)\2", re.I)
        resources, fuzzy_candidates = set(), set()
        for match in attribute.finditer(html):
            value = match.group(3)
            sound = value.startswith('sound:')
            resource = value[6:].lstrip('/') if sound else value
            if self._local_resource(resource) and os.path.splitext(self.resource_key(resource))[1].lower() in self.RESOURCE_EXTENSIONS:
                resources.add(resource)
                if sound or os.path.splitext(self.resource_key(resource))[1].lower() in {'.png', '.jpg', '.gif', '.svg', '.webp', '.jpeg'}:
                    fuzzy_candidates.add(resource)
        to_save = resources
        if not self._is_fuzzy_enabled() and not config.export_media:
            to_save = {resource for resource in resources if os.path.splitext(self.resource_key(resource))[1].lower()
                       not in {'.mp3', '.wav', '.ogg', '.aac', '.spx', '.m4a', '.flac'}}
        self.save_media_files(to_save)
        saved = getattr(self, '_media_saved', {})
        replacements = {}
        if self._is_fuzzy_enabled():
            missing = set()
            for resource in fuzzy_candidates - set(saved):
                pattern = '*\\' + posixpath.basename(self.resource_key(resource))
                if not self.builder.get_mdd_keys(pattern):
                    missing.add(resource)
            if missing:
                replacements = process_fuzzy_media(self.builder, self.title, missing, self.save_default_file)
        for resource, tag in replacements.items():
            html = re.sub(r'<a\b[^>]*\bhref=[\'"]sound:/*' + re.escape(resource) + r'[\'"][^>]*>.*?</a>',
                          lambda match: tag, html, flags=re.I | re.S)
            match = re.search(r'\bsrc="([^"]+)"', tag)
            if match:
                saved[resource] = match.group(1)

        css_classes = []
        def rewrite(match):
            attr, quote, value = match.group(1), match.group(2), match.group(3)
            if value.startswith('sound:'):
                return match.group(0)
            if value not in resources:
                return match.group(0)
            name = saved.get(value, self.media_name(value))
            if value.lower().endswith('.css'):
                path = self.media_path(name)
                if not os.path.isfile(path):
                    self.missed_css.add(value)
                wrapped, cls = wrap_css(path)
                name = os.path.basename(wrapped)
                css_classes.append(cls)
            return attr + '=' + quote + name + quote
        html = attribute.sub(rewrite, html)
        html = re.sub(r'(<style\b[^>]*>)(.*?)(</style>)',
                      lambda match: match.group(1) + self._rewrite_dependencies(match.group(2), 'inline.css') + match.group(3),
                      html, flags=re.I | re.S)
        html = re.sub(r'(\bstyle\s*=\s*)([\'"])(.*?)\2',
                      lambda match: match.group(1) + match.group(2) +
                      self._rewrite_dependencies(match.group(3), 'inline.css').replace(match.group(2), '&quot;' if match.group(2) == '"' else '&#39;') + match.group(2),
                      html, flags=re.I | re.S)
        def sound(match):
            resource = match.group(2).lstrip('/')
            name = saved.get(resource, self.media_name(resource))
            return '[sound:' + name + ']' + match.group(3)
        html = re.sub(r'<a\b[^>]*\bhref=([\'"])sound:(.*?)\1[^>]*>(.*?)</a>', sound, html, flags=re.I | re.S)
        for cls in dict.fromkeys(css_classes):
            html = '<div class="' + cls + '">' + html + '</div>'
        return html
