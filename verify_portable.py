"""Extract the release ZIP and test with Python absent from PATH/PYTHONPATH."""
import json
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='New extracted release/verification directory')
    args = parser.parse_args()
    release = json.loads((ROOT / 'latest-release.json').read_text())
    destination = args.out.resolve() if args.out else ROOT / 'releases' / release['version']
    destination.mkdir(parents=True, exist_ok=False)
    archive = destination / ('PS5-RCO-Studio-' + release['version'] + '-Windows-x64-portable.zip')
    shutil.copyfile(release['portable_zip'], archive)
    if 'source_zip' in release: shutil.copyfile(release['source_zip'], destination / Path(release['source_zip']).name)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            target = (destination / name).resolve()
            if not target.is_relative_to(destination.resolve()): raise ValueError('Unsafe ZIP member')
        bundle.extractall(destination)
    app = destination / 'PS5-RCO-Studio' / 'PS5-RCO-Studio.exe'
    env = os.environ.copy()
    env['PATH'] = str(Path(env.get('SystemRoot', r'C:\Windows')) / 'System32')
    env.pop('PYTHONPATH', None); env.pop('PYTHONHOME', None)
    result = subprocess.run([str(app), release['sample'],
                             '--self-test', '--out', str(destination / 'portable-acceptance')],
                            cwd=app.parent, env=env, timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
    acceptance = json.loads((destination / 'portable-acceptance' / 'smoke.json').read_text())
    if result.returncode or acceptance['status'] != 'PASS' or not acceptance['packaged']:
        raise RuntimeError('Extracted portable app acceptance failed')
    alias_acceptance = None
    if release.get('alias_sample'):
        alias_result = subprocess.run([str(app), release['alias_sample'], '--alias-test', '--out', str(destination / 'alias-acceptance')],
                                     cwd=app.parent, env=env, timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
        alias_acceptance = json.loads((destination / 'alias-acceptance' / 'alias-smoke.json').read_text())
        if alias_result.returncode or alias_acceptance['status'] != 'PASS': raise RuntimeError('Extracted shared-range acceptance failed')
    report = dict(status='PASS', executable=str(app), zip=str(archive), python_on_path=False,
                  python_environment_removed=True, independent_installation_tested=False,
                  packaged_acceptance=acceptance, release_identity=release)
    if alias_acceptance: report['alias_acceptance'] = alias_acceptance
    (destination / 'portable-validation.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(dict(status='PASS', executable=str(app), zip=str(archive))))


if __name__ == '__main__': main()
