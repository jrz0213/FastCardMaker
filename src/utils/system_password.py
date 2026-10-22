"""Local OS credential storage. Passwords never enter the media backup."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import shutil
import subprocess
import sys


def _target(identifier=''):
    from aqt import mw
    from pathlib import Path
    account = str(Path(mw.pm.profileFolder()).resolve()).encode('utf-8')
    return 'FastCardMaker/' + hashlib.sha256(account).hexdigest() + '/' + hashlib.sha256(identifier.encode('utf-8')).hexdigest()


def _windows(value=None, operation='read', identifier=''):
    class Credential(c.Structure):
        _fields_ = [('Flags', w.DWORD), ('Type', w.DWORD), ('TargetName', w.LPWSTR),
                    ('Comment', w.LPWSTR), ('LastWritten', w.FILETIME),
                    ('CredentialBlobSize', w.DWORD), ('CredentialBlob', c.POINTER(c.c_ubyte)),
                    ('Persist', w.DWORD), ('AttributeCount', w.DWORD), ('Attributes', c.c_void_p),
                    ('TargetAlias', w.LPWSTR), ('UserName', w.LPWSTR)]
    lib = c.WinDLL('advapi32', use_last_error=True)
    target = _target(identifier)
    if operation == 'read':
        result = c.POINTER(Credential)()
        lib.CredReadW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.POINTER(c.POINTER(Credential))]
        lib.CredReadW.restype = w.BOOL
        lib.CredFree.argtypes = [c.c_void_p]
        lib.CredFree.restype = None
        if not lib.CredReadW(target, 1, 0, c.byref(result)):
            if c.get_last_error() == 1168:  # ERROR_NOT_FOUND
                return None
            raise OSError('Cannot read the system credential store')
        try:
            return c.string_at(result.contents.CredentialBlob, result.contents.CredentialBlobSize).decode('utf-8')
        finally:
            lib.CredFree(result)
    if operation == 'delete':
        lib.CredDeleteW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD]
        lib.CredDeleteW.restype = w.BOOL
        if not lib.CredDeleteW(target, 1, 0) and c.get_last_error() != 1168:
            raise OSError('Cannot remove the system credential')
        return
    blob = value.encode('utf-8')
    if len(blob) > 2560:
        raise ValueError('Password is too long for the system credential store')
    buffer = (c.c_ubyte * len(blob)).from_buffer_copy(blob)
    item = Credential(Type=1, TargetName=target, CredentialBlobSize=len(blob),
                      CredentialBlob=buffer, Persist=2, UserName='FastCardMaker')
    lib.CredWriteW.argtypes = [c.POINTER(Credential), w.DWORD]
    lib.CredWriteW.restype = w.BOOL
    if not lib.CredWriteW(c.byref(item), 0):
        raise OSError('Cannot save the system credential')


def _mac(value=None, operation='read', identifier=''):
    security = c.CDLL('/System/Library/Frameworks/Security.framework/Security')
    core = c.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    find = security.SecKeychainFindGenericPassword
    find.argtypes = [c.c_void_p, c.c_uint32, c.c_char_p, c.c_uint32, c.c_char_p,
                     c.POINTER(c.c_uint32), c.POINTER(c.c_void_p), c.POINTER(c.c_void_p)]
    find.restype = c.c_int32
    security.SecKeychainItemFreeContent.argtypes = [c.c_void_p, c.c_void_p]
    core.CFRelease.argtypes = [c.c_void_p]
    core.CFRelease.restype = None
    service, account = b'FastCardMaker', _target(identifier).encode('utf-8')
    length, data, item = c.c_uint32(), c.c_void_p(), c.c_void_p()
    status = find(None, len(service), service, len(account), account, c.byref(length), c.byref(data), c.byref(item))
    if status not in (0, -25300):
        raise OSError('Cannot access macOS Keychain')
    try:
        if operation == 'read':
            return c.string_at(data, length.value).decode('utf-8') if status == 0 else None
        if operation == 'delete':
            if status == 0:
                delete = security.SecKeychainItemDelete
                delete.argtypes, delete.restype = [c.c_void_p], c.c_int32
                if delete(item) != 0:
                    raise OSError('Cannot remove macOS Keychain item')
            return
        blob = value.encode('utf-8')
        if status == 0:
            write = security.SecKeychainItemModifyAttributesAndData
            write.argtypes, write.restype = [c.c_void_p, c.c_void_p, c.c_uint32, c.c_char_p], c.c_int32
            result = write(item, None, len(blob), blob)
        else:
            write = security.SecKeychainAddGenericPassword
            write.argtypes = [c.c_void_p, c.c_uint32, c.c_char_p, c.c_uint32, c.c_char_p, c.c_uint32, c.c_char_p, c.c_void_p]
            write.restype = c.c_int32
            result = write(None, len(service), service, len(account), account, len(blob), blob, None)
        if result != 0:
            raise OSError('Cannot save macOS Keychain item')
    finally:
        if data.value:
            security.SecKeychainItemFreeContent(None, data)
        if item.value:
            core.CFRelease(item)


def _other(value=None, operation='read', identifier=''):
    # Use an OS-backed keyring when available; reject plaintext file backends.
    try:
        import keyring
        backend = keyring.get_keyring()
        module = type(backend).__module__
        if module.startswith(('keyring.backends.macOS', 'keyring.backends.SecretService', 'keyring.backends.kwallet')):
            if operation == 'read':
                return keyring.get_password('FastCardMaker', _target(identifier))
            if operation == 'delete':
                if keyring.get_password('FastCardMaker', _target(identifier)) is not None:
                    keyring.delete_password('FastCardMaker', _target(identifier))
            else:
                keyring.set_password('FastCardMaker', _target(identifier), value)
            return
    except ImportError:
        pass
    tool = shutil.which('secret-tool') if sys.platform.startswith('linux') else None
    if not tool:
        if operation == 'read':
            return None
        raise OSError('An OS keyring backend is required to remember this password')
    args = [tool, {'read': 'lookup', 'write': 'store', 'delete': 'clear'}[operation]]
    if operation == 'write':
        args.append('--label=FastCardMaker API Key')
    result = subprocess.run(args + ['application', 'FastCardMaker', 'account', _target(identifier)],
                            input=value.encode('utf-8') if operation == 'write' else None,
                            capture_output=True, timeout=30, check=False)
    if result.returncode:
        if operation == 'read' and result.returncode == 1:
            return None
        raise OSError('The system keyring operation failed')
    return result.stdout.decode('utf-8').removesuffix('\n') if operation == 'read' else None


def _backend():
    return _windows if sys.platform == 'win32' else _mac if sys.platform == 'darwin' else _other


def read(identifier=''):
    return _backend()(identifier=identifier)


def write(password, identifier=''):
    return _backend()(password, 'write', identifier)


def delete(identifier=''):
    return _backend()(operation='delete', identifier=identifier)
