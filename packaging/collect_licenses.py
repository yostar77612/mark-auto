"""Retain dependency license/notice texts and Python license in the bundle."""
from importlib.metadata import distributions
from pathlib import Path
import shutil
import sys

output = Path('build/licenses')
output.mkdir(parents=True, exist_ok=True)
for distribution in distributions():
    name = distribution.metadata['Name']
    for relative in distribution.files or []:
        if any(token in str(relative).lower() for token in ('license', 'copying', 'notice')):
            source = Path(distribution.locate_file(relative))
            if source.is_file():
                target = output / name / str(relative).replace('..', '_')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if not python_license.exists():
    raise RuntimeError('Python LICENSE.txt is required for distribution')
shutil.copy2(python_license, output / 'PYTHON-LICENSE.txt')
