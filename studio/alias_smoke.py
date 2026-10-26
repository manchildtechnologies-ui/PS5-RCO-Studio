"""Portable GUI acceptance for real shared-range files and synthetic image aliases."""
import json
from pathlib import Path
import struct
import time
import tkinter as tk
import zlib

from Rcomage import rcof as r
from .app import Studio
from . import __version__
from .replacement import relocation_reason


def probe_png(value):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & r.NULL)
    return r.PNG + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(bytes([0, value, 2, 3, 255]))) + chunk(b'IEND', b'')


def probe_dds(dx10=False):
    header = [0] * 31
    header[:7] = [124, 0x81007, 4, 4, 16, 0, 1]
    header[18:21] = [32, 4, struct.unpack('<I', b'DX10' if dx10 else b'DXT5')[0]]
    header[26] = 0x1000
    return b'DDS ' + struct.pack('<31I', *header) + (struct.pack('<5I', 98, 3, 0, 1, 0) if dx10 else b'') + b'\x40' + bytes(15)


def shared_probe():
    """Public synthetic fixture; no Sony bytes or filenames."""
    entries = [(probe_png(1), 'texture/png')] * 2 + [(probe_dds(), 'texture/dds')] * 2 + [(probe_dds(True), 'texture/dds')] * 2
    strings = bytearray(b'resource\0texture\0id\0type\0src\0')
    kind_offsets = {}
    for _, kind in entries:
        if kind not in kind_offsets:
            kind_offsets[kind] = len(strings); strings += kind.encode() + b'\0'
    ids, files, spans = bytearray(), bytearray(), {}
    tree = bytearray(struct.pack('<7I', 0, 0, r.NULL, r.NULL, r.NULL, 28, 28 + 76 * (len(entries) - 1)))
    for index, (payload, kind) in enumerate(entries):
        node = 28 + index * 76
        name = len(ids); ids += struct.pack('<I', node) + f'alias_probe_{index}'.encode() + b'\0'; ids += bytes((-len(ids)) % 4)
        if payload not in spans:
            files += bytes((-len(files)) % 16); spans[payload] = len(files); files += payload
        tree += struct.pack('<7I', 9, 3, 0, node - 76 if index else r.NULL,
                            node + 76 if index + 1 < len(entries) else r.NULL, r.NULL, r.NULL)
        tree += struct.pack('<4I', 17, 9, name, 0) + struct.pack('<4I', 20, 3, kind_offsets[kind], len(kind))
        tree += struct.pack('<4I', 25, 8, spans[payload], len(payload))
    data = bytearray(b'RCOF' + struct.pack('<I', 0x110) + bytes(72))
    for index, table in enumerate((tree, ids, b'', strings, b'', b'', b'', b'', files)):
        data += bytes((-len(data)) % 16); struct.pack_into('<II', data, 8 + index * 8, len(data), len(table)); data += table
    return bytes(data)


def run(sample, directory):
    out = Path(directory).resolve(); out.mkdir(parents=True, exist_ok=False)
    root = tk.Tk(); root.withdraw(); app = Studio(root)
    errors = []
    root.report_callback_exception = lambda *args: errors.append(str(args))
    from . import app as app_module
    app_module.messagebox.showerror = lambda *args, **kw: errors.append(str(args))
    report = dict(status='FAIL', version=__version__, packaged=bool(getattr(__import__('sys'), 'frozen', False)), checks=[])
    def wait():
        deadline = time.monotonic() + 240
        while app.busy and time.monotonic() < deadline: root.update(); time.sleep(.01)
        root.update(); r.require(not app.busy and not errors, 'GUI acceptance error: ' + str(errors))
    def task(label, work, done=lambda _: None):
        app.submit(label, work, done); wait(); report['checks'].append(label)
    def select(ident):
        app.tree.selection_set(ident); app.select(); root.update()
    try:
        app.open_path(sample); wait(); original_session = app.session
        r.require(original_session is not None and original_session.container.alias_groups, 'Expected an exact-shared-range sample')
        report.update(sample_sha256=r.sha(original_session.original), resources=len(original_session.resources),
                      shared_groups=original_session.container.alias_groups)
        for group in original_session.container.alias_groups:
            for ident in group['resource_ids']:
                select(ident)
                r.require('shared_with' in app.metadata.get('1.0', 'end'), 'GUI omitted shared-reference metadata')
        task('Extract all real shared resources', lambda: original_session.export_all(out / 'raw'), lambda result: report.update(extracted=result))
        task('Reconstruct extracted shared resources without changes', lambda: r.repack(report['extracted']['directory']),
             lambda data: r.require(data == original_session.original, 'Shared extraction/repack differs from original'))
        task('Byte-identical GUI rebuild preserving every shared pointer', lambda: original_session.rebuild(out / 'builds'), app.built)
        r.require(original_session.last_report['byte_identical'], 'Shared no-change rebuild differs')
        report['no_change'] = original_session.last_report
        eligible = [x for x in original_session.container.resources if x['kind'] == 'png' and x['replacement_supported'] and relocation_reason(original_session.container, x) is None]
        if eligible:
            item = eligible[0]; payload = original_session.payload(item['id'])
            comment = b'AliasAcceptance\0Unshared PNG edit must preserve all pooled references'
            chunk = struct.pack('>I', len(comment)) + b'tEXt' + comment + struct.pack('>I', zlib.crc32(b'tEXt' + comment) & r.NULL)
            edited = payload[:-12] + chunk + payload[-12:]; path = out / 'actual-replacement.png'; r.write_new(path, edited)
            task('Edit a real PNG without disturbing shared SVG/compressed resources', lambda: original_session.stage(item['id'], path), app.staged)
            task('Reopen and validate all real resources after edit', lambda: original_session.rebuild(out / 'builds'), app.built)
            report['real_png_edit'] = original_session.last_report
        original_session.unchanged_source()
        probe = out / 'synthetic-shared-images.rco'; r.write_new(probe, shared_probe())
        app.open_path(probe); wait(); session = app.session
        r.require(len(session.container.alias_groups) == 3, 'Synthetic PNG/DDS sharing fixture failed')
        task('Synthetic shared PNG/DXT5/BC7 no-change rebuild', lambda: session.rebuild(out / 'synthetic-builds'), app.built)
        r.require(session.last_report['byte_identical'], 'Synthetic shared no-change identity failed')
        changes = {'r00000': probe_png(2), 'r00002': probe_dds()[:-1] + b'\1', 'r00004': probe_dds(True)[:-1] + b'\1'}
        paths = {}
        for ident, payload in changes.items():
            path = out / (ident + '.replacement'); r.write_new(path, payload); paths[ident] = path
        task('Stage three independent shared PNG/DDS edits atomically', lambda: session.stage_multiple(paths), app.imported)
        task('Copy-on-write rebuild and every-reference validation', lambda: session.rebuild(out / 'synthetic-builds'), app.built)
        cow = session.last_report; report['synthetic_copy_on_write'] = cow
        r.require(len(cow['relocations']) == 3 and all(x['copy_on_write'] for x in cow['relocations']), 'Expected three copy-on-write allocations')
        built = cow['output']; app.open_path(built); wait()
        for item in session.container.resources:
            expected = changes.get(item['id'], session.original[item['offset']:item['offset'] + item['size']])
            r.require(app.session.payload(item['id']) == expected, 'Reopened alias/sibling contents differ')
        for ident in changes:
            select(ident); r.require(app.photo is not None, 'Copy-on-write preview failed')
        partial = bytearray(shared_probe()); c = r.Container(bytes(partial))
        struct.pack_into('<I', partial, c.resources[1]['attribute_offset'] + 8, c.resources[0]['relative_offset'] + 16)
        partial_path = out / 'synthetic-partial-overlap.rco'; r.write_new(partial_path, partial)
        app.open_path(partial_path); wait(); select('r00000')
        r.require(app.session.container.read_only and str(app.build_button['state']) == 'disabled', 'Partial overlap writer was not blocked')
        task('Read-only raw extraction remains available for unverified overlaps', lambda: app.session.export_all(out / 'partial-extraction'))
        original_session.unchanged_source()
        report.update(status='PASS', errors=errors, original_unchanged=True, console_contacted=False, console_acceptance='UNTESTED')
    except Exception as exc: report['error'] = str(exc)
    finally:
        r.write_new(out / 'alias-smoke.json', r.json_bytes(report))
        if not app.busy: root.destroy()
    return 0 if report['status'] == 'PASS' else 1
