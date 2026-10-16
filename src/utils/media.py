"""Explicit profile media paths, including a token to reject stale query writes."""

import os

from aqt import mw


def profile_token():
    from ..context import config
    generation = getattr(config, 'generation', 0)
    return os.path.normcase(os.path.abspath(mw.pm.profileFolder())), generation


def media_directory():
    return os.path.join(mw.pm.profileFolder(), 'collection.media')


def media_path(filename, directory=None):
    if os.path.isabs(filename):
        return filename
    directory = directory or media_directory()
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, filename)
