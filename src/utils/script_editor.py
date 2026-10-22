"""Open Python source as text, never through the executable file association."""
from pathlib import Path
import shutil
import subprocess
import sys


def open_script(path):
    path = Path(path).resolve()
    if path.suffix.lower() != '.py' or not path.is_file():
        raise ValueError('Python script is unavailable')
    if sys.platform == 'win32':
        command = ['notepad.exe', str(path)]
    elif sys.platform == 'darwin':
        command = ['open', '-e', str(path)]
    else:
        editor = next((found for name in ('gedit', 'kate', 'xed', 'mousepad', 'leafpad', 'code')
                       if (found := shutil.which(name))), None)
        if not editor:
            raise OSError('No graphical text editor is available')
        command = [editor, str(path)]
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
