"""Build a portable Windows folder, test the frozen executable, then ZIP it.

Run with the local Python containing PyInstaller 6.22.3 and Pillow 11.3.0.
All build artifacts go beneath the lab. No downloads or installations.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from studio import __version__
from source_bundle import create_source_archive, audit_names

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample', required=True, type=Path)
    parser.add_argument('--alias-sample', type=Path, help='Optional second real RCO for shared-range acceptance')
    args = parser.parse_args()
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    run = ROOT / 'builds' / name
    run.mkdir(parents=True)
    env = os.environ.copy()
    env['PYINSTALLER_CONFIG_DIR'] = str(run / 'cache')
    version_file = run / 'version-info.txt'
    numeric_version = tuple(map(int, __version__.split('.'))) + (0,)
    version_file.write_text(
        'VSVersionInfo(ffi=FixedFileInfo(filevers=' + repr(numeric_version) +
        ', prodvers=' + repr(numeric_version) +
        ", mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), kids=["
        "StringFileInfo([StringTable('040904B0', [StringStruct('FileDescription', 'PS5 RCO Studio'), "
        "StringStruct('ProductName', 'PS5 RCO Studio'), StringStruct('FileVersion', '" + __version__ +
        "'), StringStruct('ProductVersion', '" + __version__ + "')])]), "
        "VarFileInfo([VarStruct('Translation', [1033,1200])])])", encoding='utf-8')
    command = [sys.executable, '-m', 'PyInstaller', '--onedir', '--windowed', '--name', 'PS5-RCO-Studio',
               '--version-file', str(version_file),
               '--distpath', str(run / 'dist'), '--workpath', str(run / 'work'), '--specpath', str(run),
               '--hidden-import', 'PIL.DdsImagePlugin', '--hidden-import', 'PIL.PngImagePlugin',
               '--exclude-module', 'matplotlib', '--exclude-module', 'numpy', '--exclude-module', 'pytest',
               str(ROOT / 'ps5_rco_studio.py')]
    with (run / 'build.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    app = run / 'dist' / 'PS5-RCO-Studio'
    executable = app / 'PS5-RCO-Studio.exe'
    shutil.copyfile(ROOT / f'USER-GUIDE-{__version__}.md', app / 'README.md')
    for filename in (f'COMPATIBILITY-{__version__}.md', f'RELEASE-NOTES-{__version__}.md', 'THIRD-PARTY-AUDIT.md'):
        shutil.copyfile(ROOT / filename, app / filename)
    (app / 'VERSION.txt').write_text(__version__ + '\n')
    licenses = app / 'licenses'; licenses.mkdir()
    for path in (ROOT / 'third_party_notices').iterdir():
        if path.is_file(): shutil.copyfile(path, licenses / path.name)
    for package in ('Pillow', 'PyInstaller'):
        distribution = importlib.metadata.distribution(package)
        for file in distribution.files or []:
            if 'license' in str(file).lower() or Path(file).name.lower().startswith('copying'):
                original = Path(distribution.locate_file(file))
                if original.is_file():
                    target = licenses / (package + '-' + str(file).replace('/', '_').replace('\\', '_'))
                    shutil.copyfile(original, target)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.exists(): shutil.copyfile(python_license, licenses / 'Python-LICENSE.txt')
    for folder in ('tcl8.6', 'tk8.6'):
        license_path = Path(sys.base_prefix) / 'tcl' / folder / 'license.terms'
        if license_path.exists(): shutil.copyfile(license_path, licenses / (folder + '-license.terms'))
    source_archive, source_hashes = create_source_archive(run, __version__)
    runtime_files = {p.relative_to(app).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in app.rglob('*') if p.is_file()}
    audit_names(runtime_files)
    (run / 'runtime-inventory.json').write_text(json.dumps(runtime_files, indent=2))
    probe = subprocess.run([str(executable), str(args.sample.resolve()), '--self-test', '--out', str(run / 'acceptance')],
                           cwd=run, timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
    report = json.loads((run / 'acceptance' / 'smoke.json').read_text())
    if probe.returncode != 0 or report['status'] != 'PASS':
        raise RuntimeError('Frozen GUI acceptance failed; retained build and reports at ' + str(run))
    if args.alias_sample:
        alias_probe = subprocess.run([str(executable), str(args.alias_sample.resolve()), '--alias-test', '--out', str(run / 'alias-acceptance')],
                                     cwd=run, timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
        alias_report = json.loads((run / 'alias-acceptance' / 'alias-smoke.json').read_text())
        if alias_probe.returncode or alias_report['status'] != 'PASS':
            raise RuntimeError('Frozen shared-range acceptance failed: ' + str(alias_report.get('error')))
    archive = Path(shutil.make_archive(str(run / ('PS5-RCO-Studio-' + __version__ + '-Windows-x64-portable')), 'zip', run / 'dist'))
    identity = dict(status='PASS', version=__version__, sample=str(args.sample.resolve()), executable=str(executable), portable_zip=str(archive),
                    source_zip=str(source_archive), source_zip_sha256=hashlib.sha256(source_archive.read_bytes()).hexdigest(),
                    sample_extensions_excluded=True, source_files=len(source_hashes),
                    zip_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                    exe_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                    sample_acceptance=str(run / 'acceptance' / 'smoke.json'),
                    python=sys.version, pillow=importlib.metadata.version('Pillow'),
                    pyinstaller=importlib.metadata.version('PyInstaller'))
    if args.alias_sample:
        identity.update(alias_sample=str(args.alias_sample.resolve()), alias_acceptance=str(run / 'alias-acceptance' / 'alias-smoke.json'))
    (run / 'release.json').write_text(json.dumps(identity, indent=2))
    (ROOT / 'latest-release.json').write_text(json.dumps(identity, indent=2))
    print(json.dumps(identity, indent=2))


if __name__ == '__main__':
    main()
