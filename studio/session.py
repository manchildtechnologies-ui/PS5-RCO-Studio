"""GUI application service. All resource parsing/patching uses the tested backend."""
from datetime import datetime, timezone
import io
from pathlib import Path
import uuid

from PIL import Image
from Rcomage import rcof
from .replacement import compose, relocation_reason, validate_rebuild
from . import project, nested


class Session:
    def __init__(self, source):
        self.source = Path(source).resolve(strict=True)
        self.original = rcof.read_file(self.source)
        self.container = rcof.Container(self.original, read_only_overlaps=True)
        self.current_container = self.container
        self.original_resources = {r['id']: r for r in self.container.resources}
        self.resources = {r['id']: r for r in self.container.resources}
        self.working = self.original
        self.pending = {}
        self.last_report = None
        self._hierarchy_cache = {}
        self._nodes = {n['offset']: n for n in self.container.nodes}

    def unchanged_source(self):
        rcof.require(rcof.sha(rcof.read_file(self.source)) == rcof.sha(self.original),
                     'Original file changed externally. Reopen it before continuing.')

    def resource(self, identifier):
        rcof.require(identifier in self.resources, 'Select a resource first.')
        return self.resources[identifier]

    def payload(self, identifier):
        item = self.resource(identifier)
        return self.working[item['offset']:item['offset'] + item['size']]

    def preview(self, identifier, bounds=(720, 480), original=False):
        item = self.original_resources[identifier] if original else self.resource(identifier)
        rcof.require(item['kind'] in ('png', 'dds') and item['image'] is not None,
                     item['unsupported_reason'] or 'Preview unsupported for this resource.')
        info = item['image']
        rcof.require(info['width'] * info['height'] * 8 <= rcof.MAX_DECODE,
                     'Preview exceeds decoded image memory limit.')
        payload = self.original[item['offset']:item['offset'] + item['size']] if original else self.payload(identifier)
        with Image.open(io.BytesIO(payload)) as decoded:
            decoded.load()
            result = decoded.convert('RGBA')
            result.thumbnail(bounds, Image.Resampling.LANCZOS)
            return result

    def stage(self, identifier, replacement_path):
        self.unchanged_source()
        self.resource(identifier)
        item = self.original_resources[identifier]
        rcof.require(item['replacement_supported'], 'Replacement unsupported: ' + str(item['unsupported_reason']))
        payload = rcof.read_file(replacement_path)
        pending = dict(self.pending)
        if payload == self.original[item['offset']:item['offset'] + item['size']]:
            pending.pop(identifier, None)
        else:
            pending[identifier] = payload
        updated, parsed, validation = compose(self.original, pending)
        self.unchanged_source()
        # Commit only after the entire candidate layout and every resource passed.
        self.working, self.pending, self.current_container = updated, pending, parsed
        self.resources = {r['id']: r for r in parsed.resources}
        self.last_report = None
        current = self.resource(identifier)
        return dict(resource_id=identifier, name=item['name'], original_size=item['size'],
                    size=current['size'], offset=current['offset'],
                    mode='shared-copy-on-write' if current['offset'] != item['offset'] and item.get('shared_with') else
                         'png-relocation' if current['offset'] != item['offset'] else 'fixed-size-patch',
                    input_sha256=rcof.sha(self.original), output_sha256=rcof.sha(updated),
                    non_target_bytes_identical=True, relocations=validation['relocations'])

    def stage_multiple(self, replacements):
        self.unchanged_source()
        pending = dict(self.pending)
        for identifier, path in replacements.items():
            self.resource(identifier)
            item = self.original_resources[identifier]
            rcof.require(item['replacement_supported'], identifier + ': replacement unsupported.')
            payload = rcof.read_file(path)
            if payload == self.original[item['offset']:item['offset'] + item['size']]: pending.pop(identifier, None)
            else: pending[identifier] = payload
        updated, parsed, validation = compose(self.original, pending)
        self.unchanged_source()
        self.working, self.pending, self.current_container = updated, pending, parsed
        self.resources = {r['id']: r for r in parsed.resources}; self.last_report = None
        return dict(changed_resources=sorted(pending), staged=len(pending), relocations=validation['relocations'])

    def export_project(self, directory):
        self.unchanged_source()
        target = self.output_directory(directory) / ('extracted-project-' + uuid.uuid4().hex[:12])
        report = project.export_project(self.original, self.pending, target)
        self.unchanged_source()
        return report

    @classmethod
    def open_project(cls, directory):
        root, _, _ = project.read_project(directory)
        return cls(root / 'baseline.rco')

    def scan_project(self, directory, progress=None):
        report, _, original = project.scan_project(directory, progress)
        rcof.require(original == self.original, 'Extracted folder belongs to a different original RCO.')
        return report

    def import_project(self, directory, progress=None):
        report, payloads, original = project.scan_project(directory, progress)
        rcof.require(original == self.original, 'Extracted folder belongs to a different original RCO.')
        rcof.require(report['status'] == 'READY', 'Reimport blocked: missing or additional files, or unsupported modifications. ' +
                    str(dict(missing=report['missing'][:10], additional=report['additional'][:10],
                             unsupported_modified=report['unsupported_modified'][:10])))
        self.unchanged_source()
        updated, parsed, validation = compose(self.original, payloads)
        self.unchanged_source()
        self.working, self.pending, self.current_container = updated, payloads, parsed
        self.resources = {r['id']: r for r in parsed.resources}; self.last_report = None
        return dict(**report, staged=len(payloads), relocations=validation['relocations'])

    def validate(self):
        self.unchanged_source()
        _, details = validate_rebuild(self.original, self.working, self.pending)
        return dict(status='PASS', resource_count=len(self.resources), original_unchanged=True,
                    console_acceptance='UNTESTED', **details)

    def hierarchy(self, identifier):
        if identifier in self._hierarchy_cache: return self._hierarchy_cache[identifier]
        item = self.resource(identifier)
        nodes = self._nodes
        node, parts = nodes[item['node_offset']], []
        while True:
            parts.append(node['name'] or node['tag'])
            if node['parent'] == rcof.NULL: break
            node = nodes[node['parent']]
        result = '/'.join(reversed(parts)) + '/' + item['attribute']
        self._hierarchy_cache[identifier] = result
        return result

    def inspect_nested(self, identifier):
        item = self.resource(identifier)
        return nested.inspect(self.payload(identifier), item['kind'])

    def export_nested(self, identifier, directory):
        self.unchanged_source()
        item = self.resource(identifier)
        target = self.output_directory(directory) / ('nested-' + identifier + '-' + uuid.uuid4().hex[:8])
        report = nested.export(self.payload(identifier), item['kind'], target)
        self.unchanged_source()
        return report

    def stage_string(self, identifier, string_id, text):
        item = self.resource(identifier)
        rcof.require(item['kind'] == 'rcsf', 'Nested editing is supported only for verified RCSF strings.')
        candidate = nested.replace_string(self.payload(identifier), string_id, text)
        self.unchanged_source()
        pending = dict(self.pending)
        base = self.original_resources[identifier]
        if candidate == self.original[base['offset']:base['offset'] + base['size']]: pending.pop(identifier, None)
        else: pending[identifier] = candidate
        updated, parsed, validation = compose(self.original, pending)
        self.unchanged_source()
        self.working, self.pending, self.current_container = updated, pending, parsed
        self.resources = {r['id']: r for r in parsed.resources}
        return dict(changed_resources=sorted(pending), staged=len(pending), relocations=validation['relocations'])

    def relocation_reason(self, identifier):
        item = self.original_resources[identifier]
        return relocation_reason(self.container, item, copy_on_write=bool(item.get('shared_with')))

    def reset(self):
        self.working = self.original
        self.pending.clear()
        self.current_container = self.container
        self.resources = dict(self.original_resources)
        self.last_report = None

    def output_directory(self, directory):
        destination = Path(directory).resolve()
        rcof.require(destination != self.source.parent,
                     'Choose a separate output folder, not the original file folder.')
        destination.mkdir(parents=True, exist_ok=True)
        return destination

    def export_one(self, identifier, directory):
        self.unchanged_source()
        item = self.resource(identifier)
        directory = self.output_directory(directory)
        filename = Path(item['file']).name
        target = directory / filename
        rcof.write_new(target, self.payload(identifier))
        self.unchanged_source()
        return target

    def export_all(self, directory):
        self.unchanged_source()
        directory = self.output_directory(directory)
        target = directory / ('extracted-' + uuid.uuid4().hex[:12])
        summary = rcof.extract(self.working, target, read_only_overlaps=self.container.read_only)
        self.unchanged_source()
        return dict(directory=str(target), **summary)

    def save_as(self, path):
        path = Path(path).resolve()
        rcof.require(path.suffix.lower() == '.rco', 'Save As requires an .rco filename.')
        return self.rebuild(path.parent, output_path=path)

    def rebuild(self, directory, output_path=None):
        self.unchanged_source()
        data, parsed, validation = compose(self.original, self.pending)
        rcof.require(data == self.working, 'Staging/reconstruction disagreement.')
        destination = self.output_directory(directory)
        if output_path is None:
            run = destination / ('build-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
            run.mkdir()
            target = run / (self.source.stem + '.rebuilt.rco')
            report_path = run / 'validation.json'
        else:
            target = Path(output_path).resolve()
            rcof.require(target.parent == destination and not target.exists(), 'Save As target must be a new file in the output folder.')
            report_path = target.with_name(target.name + '.validation.json')
            rcof.require(not report_path.exists(), 'Save As validation report already exists.')
        report = dict(status='FAIL', original=str(self.source), output=str(target),
                      console_acceptance='UNTESTED', console_contacted=False)
        try:
            rcof.write_new(target, data)
            reread = rcof.read_file(target)
            rcof.require(reread == data, 'Output readback differs from reconstruction.')
            parsed, validation = validate_rebuild(self.original, reread, self.pending)
            self.unchanged_source()
            report.update(status='PASS', mode='shared-copy-on-write' if any(x['copy_on_write'] for x in validation['relocations']) else
                          'png-relocation' if validation['relocations'] else
                          'fixed-size-patch' if self.pending else 'no-change-reconstruction',
                          original_sha256=rcof.sha(self.original), output_sha256=rcof.sha(reread),
                          original_size=len(self.original), output_size=len(reread),
                          byte_identical=reread == self.original, resource_count=len(parsed.resources),
                          changed_resources=sorted(self.pending), non_target_bytes_identical=True,
                          original_unchanged=True, **{k: v for k, v in validation.items() if k != 'non_target_bytes_identical'})
        except Exception as exc:
            report['error'] = str(exc)
            raise
        finally:
            rcof.write_new(report_path, rcof.json_bytes(report))
            self.last_report = report
        return report
