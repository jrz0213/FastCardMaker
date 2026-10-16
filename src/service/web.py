"""HTTP requests and downloads for online dictionaries."""

import urllib.parse

import requests

from .core import Service
from ..utils.media import media_path


_default_ua = 'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 ' \
              '(KHTML, like Gecko) Chrome/70.0.3538.67 Safari/537.36'

class WebService(Service):
    def __init__(self):
        super(WebService, self).__init__()
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': _default_ua})
        self.query_interval = 1.0

    @property
    def title(self):
        return getattr(self, '__register_label__', self.unique)

    def get_response(self, url, data=None, headers=None, timeout=10):
        req_headers = headers if headers else {}
        try:
            if data:
                response = self.session.post(url, data=data, headers=req_headers, timeout=timeout)
            else:
                response = self.session.get(url, headers=req_headers, timeout=timeout)
            response.raise_for_status()
            return response.content
        except Exception as e:
            return b''

    @classmethod
    def download(cls, url, filename, timeout=15):
        try:
            destination = media_path(filename)
            response = requests.get(url, headers={'User-Agent': _default_ua}, timeout=timeout)
            response.raise_for_status()
            with open(destination, "wb") as f:
                f.write(response.content)
            return True
        except Exception:
            return False

    class TinyDownloadError(ValueError):
        pass

    def net_stream(self, targets, require=None, method='GET', awesome_ua=False, add_padding=False, custom_quoter=None, custom_headers=None):
        DEFAULT_TIMEOUT = 3
        PADDING = b'\0' * 2 ** 11
        targets = targets if isinstance(targets, list) else [targets]
        processed_targets = []
        for target in targets:
            if isinstance(target, str):
                processed_targets.append((target, None))
            else:
                url, params_dict = target[0], target[1]
                param_strs = []
                for key, val in params_dict.items():
                    quoter = custom_quoter[key] if (custom_quoter and key in custom_quoter) else urllib.parse.quote
                    encoded_val = quoter(val.encode('utf-8') if isinstance(val, str) else str(val), safe='')
                    param_strs.append(f"{key}={encoded_val}")
                processed_targets.append((url, '&'.join(param_strs)))

        require = require or {}
        payloads = []
        for number, (url, params) in enumerate(processed_targets, 1):
            desc = "web request"
            headers = {}
            if custom_headers:
                headers.update(custom_headers)
            try:
                if method == 'GET':
                    req_url = '?'.join([url, params]) if params else url
                    response = self.session.get(req_url, headers=headers, timeout=DEFAULT_TIMEOUT)
                else:
                    response = self.session.post(url, data=params, headers=headers, timeout=DEFAULT_TIMEOUT)
                if response.status_code != 200:
                    raise ValueError(f"Got {response.status_code} status")
                content_type = response.headers.get('Content-Type', '')
                if 'mime' in require and require['mime'] not in content_type.replace('/x-', '/'):
                    raise ValueError(f"Wanted mime {require['mime']}")
                payload = response.content
                if 'size' in require and len(payload) < require['size']:
                    raise self.TinyDownloadError("Download too small")
                payloads.append(payload)
            except Exception as e:
                raise IOError(str(e))
        if add_padding:
            payloads.append(PADDING)
        return b''.join(payloads)

    def net_download(self, path, *args, **kwargs):
        try:
            payload = self.net_stream(*args, **kwargs)
            with open(self.media_path(path), 'wb') as f:
                f.write(payload)
            return True
        except Exception:
            return False
