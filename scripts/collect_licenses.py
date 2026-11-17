"""Saml licenstekster til de biblioteker, installeren distribuerer."""
from importlib.metadata import distribution
from pathlib import Path
import sys


root = Path(__file__).resolve().parents[1]
sections = []


def include(label, path):
    sections.append(f'{label}\n{"=" * len(label)}\n\n{path.read_text(encoding="utf-8", errors="replace")}')


for package in ('numpy', 'sounddevice', 'cffi', 'pycparser', 'pyinstaller'):
    installed = distribution(package)
    license_files = [file for file in installed.files or []
                     if 'license' in file.name.lower() or 'copying' in file.name.lower()]
    if not license_files:
        raise RuntimeError(f'Mangler licens for {package}')
    for file in license_files:
        include(f'{package} {installed.version}: {file}', installed.locate_file(file))

include('PortAudio, https://github.com/PortAudio/portaudio', root / 'third-party/PortAudio-LICENSE.txt')
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.exists():
    include(f'Python {sys.version.split()[0]}', python_license)
elif sys.platform == 'win32':
    raise RuntimeError('Mangler Python LICENSE.txt')

for path in sorted((Path(sys.base_prefix) / 'tcl').rglob('*')):
    if path.is_file() and path.name.lower().startswith(('license', 'copying')):
        include(f'Tcl/Tk: {path.relative_to(sys.base_prefix)}', path)

output = root / 'dist/THIRD-PARTY-LICENSES.txt'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text('\n\n'.join(sections), encoding='utf-8')
print(f'{len(sections)} licenstekster samlet i {output.name}')
