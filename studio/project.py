"""Self-contained editable resource folders with canonical metadata validation."""
import json
from pathlib import Path
from Rcomage import rcof as r


def canonical(data):
    container = r.Container(data, read_only_overlaps=True)
    manifest = container.manifest()
    layout = bytearray(data)
    for item in container.resources:
        layout[item['offset']:item['offset'] + item['size']] = bytes(item['size'])
    manifest['layout_sha256'] = r.sha(layout)
    return container, manifest, bytes(layout)


def export_project(original, current_payloads, directory):
    root = Path(directory)
    r.require(not root.exists(), 'Extracted project directory must be new.')
    container, manifest, layout = canonical(original)
    r.require(not container.read_only or not current_payloads, 'Read-only overlapping projects cannot contain staged edits.')
    root.mkdir(parents=True); (root / 'resources').mkdir()
    r.write_new(root / 'baseline.rco', original)
    r.write_new(root / 'layout.bin', layout)
    manifest_data = r.json_bytes(manifest)
    r.write_new(root / 'manifest.json', manifest_data)
    r.write_new(root / 'project.json', r.json_bytes(dict(schema='ps5-rco-studio-project-1',
                original_sha256=r.sha(original), manifest_sha256=r.sha(manifest_data), layout_sha256=r.sha(layout))))
    for item in container.resources:
        payload = current_payloads.get(item['id'], original[item['offset']:item['offset'] + item['size']])
        r.write_new(root / item['file'], payload)
    return dict(directory=str(root), resources=len(container.resources), baseline_sha256=r.sha(original))


def read_project(directory):
    root = Path(directory).resolve(strict=True)
    read = lambda p: r.read_file(r.child_file(root, p))
    data = read('baseline.rco')
    container, expected, layout = canonical(data)
    project = json.loads(read('project.json'))
    expected_project = dict(schema='ps5-rco-studio-project-1', original_sha256=r.sha(data),
                            manifest_sha256=r.sha(r.json_bytes(expected)), layout_sha256=r.sha(layout))
    r.require(project == expected_project, 'Project metadata/baseline identity changed.')
    manifest_bytes = read('manifest.json')
    r.require(r.sha(manifest_bytes) == project['manifest_sha256'] and json.loads(manifest_bytes) == expected,
              'Manifest changed. Resource paths, offsets, sizes and references must not be edited.')
    r.require(read('layout.bin') == layout, 'Preservation layout changed.')
    return root, data, container


def scan_project(directory, progress=None):
    root, original, container = read_project(directory)
    known = {'project.json', 'baseline.rco', 'manifest.json', 'layout.bin'}
    known.update(x['file'] for x in container.resources)
    # Paths are checked before any external payload read. Reparse links are never followed.
    actual = set()
    for path in root.rglob('*'):
        r.require(not path.is_symlink() and not (hasattr(path, 'is_junction') and path.is_junction()),
                  'Linked paths in extracted projects are unsupported.')
        if path.is_file(): actual.add(path.relative_to(root).as_posix())
    missing, additional = sorted(known - actual), sorted(actual - known)
    modified, unchanged, payloads, unsupported = [], [], {}, []
    for index, item in enumerate(container.resources):
        if item['file'] not in actual: continue
        payload = r.read_file(r.child_file(root, item['file']))
        if r.sha(payload) != item['sha256']:
            supported = not container.read_only and (item['replacement_supported'] or (item['kind'] == 'rcsf' and item['compression'] == 'stored'))
            modified.append(dict(id=item['id'], name=item['name'], kind=item['kind'],
                                 old_size=item['size'], new_size=len(payload), file=item['file'],
                                 supported_for_validation=supported))
            if not supported: unsupported.append(item['file'])
            payloads[item['id']] = payload
        else:
            unchanged.append(item['id'])
        if progress and index % 100 == 0: progress(index + 1, len(container.resources))
    return dict(directory=str(root), original_sha256=r.sha(original), modified=modified,
                unchanged=unchanged, missing=missing, additional=additional,
                unsupported_modified=unsupported,
                read_only=container.read_only,
                status='READ_ONLY' if container.read_only else 'READY' if not missing and not additional and not unsupported else 'BLOCKED'), payloads, original
