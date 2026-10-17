"""Check local dependencies without downloading media or encoding video."""
import importlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    errors = []
    print(f'Python: {platform.python_version()} ({platform.machine()})')
    if sys.version_info < (3, 10):
        errors.append('Python 3.10+ is required.')
    for name in ('curl_cffi', 'PIL'):
        try:
            module = importlib.import_module(name)
            print(f'{name}: {module.__version__}')
        except (ImportError, OSError) as error:
            errors.append(f'{name}: {error}; rerun setup.cmd.')
    for name in ('ffmpeg', 'ffprobe', 'curl.exe'):
        tool = shutil.which(name)
        if not tool:
            errors.append(f'{name} missing from PATH.')
            continue
        try:
            result = subprocess.run([tool, '-version' if name != 'curl.exe' else '--version'],
                                    capture_output=True, text=True, timeout=15, errors='replace')
            if result.returncode:
                errors.append(f'{name} cannot start: {result.stderr[:200]}')
            else:
                print(f'{name}: {tool}')
        except (OSError, subprocess.TimeoutExpired) as error:
            errors.append(f'{name}: {error}')
    for name in ('bia_new.jpg', 'tiem-phim-gio-com-watermark.png'):
        if not (root / 'assets/fanpage' / name).is_file():
            errors.append(f'Missing asset: assets/fanpage/{name}')
    fonts = (root / 'assets/fonts/DejaVuSans-Bold.ttf', Path('C:/Windows/Fonts/arialbd.ttf'),
             Path('C:/Windows/Fonts/segoeuib.ttf'),
             Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
    if not any(font.is_file() for font in fonts):
        errors.append('No default cover font found; supply --cover-font PATH when running.')
    if errors:
        for error in errors:
            print(f'ERROR: {error}')
        return 1
    print('Local dependencies OK. GPU is optional; network/source availability is not tested.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
