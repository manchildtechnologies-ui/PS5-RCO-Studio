"""Explicit source allowlist. Never package local Sony resources or baselines."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
FORBIDDEN = {'.rco', '.rcsf', '.dds'}


def audit_names(names):
    for name in names:
        path = Path(name)
        if path.suffix.lower() in FORBIDDEN or path.name.lower() in ('rcomage.exe', 'gimconv.exe', 'baseline.rco'):
            raise ValueError('Forbidden proprietary/sample artifact in release: ' + name)
        if path.is_absolute() or '..' in path.parts: raise ValueError('Unsafe archive path: ' + name)


def create_source_archive(destination, version):
    files = [*ROOT.glob('studio/*.py'), *ROOT.glob('research/*.py'), *ROOT.glob('tests/test_*.py'),
             ROOT / 'Rcomage/rcof.py', ROOT / 'ps5_rco_studio.py', ROOT / 'build_portable.py',
             ROOT / 'verify_portable.py', ROOT / 'source_bundle.py',
             *ROOT.glob('requirements-*.txt'), ROOT / '.gitignore', ROOT / 'THIRD-PARTY-AUDIT.md',
             ROOT / f'USER-GUIDE-{version}.md', ROOT / f'COMPATIBILITY-{version}.md', ROOT / f'RELEASE-NOTES-{version}.md',
             *ROOT.glob('third_party_notices/*')]
    archive = Path(destination) / ('PS5-RCO-Studio-' + version + '-source.zip')
    manifest = {}
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files):
            if not path.is_file(): continue
            name = path.relative_to(ROOT).as_posix(); audit_names([name])
            bundle.write(path, name)
            manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        bundle.write(ROOT / f'USER-GUIDE-{version}.md', 'README.md')
        bundle.writestr('SOURCE-SHA256.json', json.dumps(manifest, indent=2))
        bundle.writestr('LICENSE-STATUS.txt', 'Project source license has not been selected by the maintainer.\n'
                         'Third-party notices retain their own terms. See THIRD-PARTY-AUDIT.md.\n')
    with zipfile.ZipFile(archive) as bundle: audit_names(bundle.namelist())
    return archive, manifest
