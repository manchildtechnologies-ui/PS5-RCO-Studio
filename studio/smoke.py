"""GUI and packaged-app acceptance probe; no network or console access."""
import io
import json
from pathlib import Path
import struct
import time
import tkinter as tk
import zlib

from PIL import Image
from Rcomage import rcof
from .app import Studio
from . import __version__


def png_chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & rcof.NULL)


def size_change_probes(payload):
    """Compatible pixel-modified probes for the sample's first RGBA PNG."""
    info = rcof.png_info(payload)
    rcof.require(info['bit_depth'] == 8 and info['color_type'] == 6 and info['interlace'] == 0,
                 'Size-change acceptance probe expects the sample RGBA8 PNG.')
    modified = changed_png(payload)
    # Exercise a genuinely different IDAT length, not just an ancillary chunk.
    with Image.open(io.BytesIO(modified)) as image:
        image.load()
        buffer = io.BytesIO(); image.save(buffer, format='PNG', compress_level=0)
        larger = buffer.getvalue()
    ihdr = struct.pack('>IIBBBBB', info['width'], info['height'], 8, 6, 0, 0, 0)
    raw = bytes((info['width'] * 4 + 1) * info['height'])
    smaller = rcof.PNG + png_chunk(b'IHDR', ihdr) + png_chunk(b'IDAT', zlib.compress(raw, 9)) + png_chunk(b'IEND', b'')
    rcof.require(len(smaller) < len(payload) < len(larger), 'Probe images do not bracket the original size.')
    return larger, smaller


def changed_png(payload):
    # Only used for the sample's small RGBA first texture.
    p, parts, streams = 8, [], []
    while p < len(payload):
        n = struct.unpack_from('>I', payload, p)[0]
        kind, data = payload[p + 4:p + 8], payload[p + 8:p + 8 + n]
        parts.append((kind, data))
        if kind == b'IDAT': streams.append(data)
        p += n + 12
    raw = zlib.decompress(b''.join(streams))
    for index in range(1, min(32, len(raw))):
        for value in range(256):
            if value == raw[index]: continue
            candidate = bytearray(raw); candidate[index] = value
            for level in (1, 6, 9):
                compressed = zlib.compress(candidate, level)
                if len(compressed) != sum(map(len, streams)): continue
                result, wrote = bytearray(rcof.PNG), False
                for kind, data in parts:
                    if kind == b'IDAT':
                        if wrote: continue
                        data, wrote = compressed, True
                    result += struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & rcof.NULL)
                rcof.png_info(result)
                if len(result) == len(payload): return bytes(result)
    raise ValueError('No compatible PNG candidate found')


def run(sample, out):
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=False)
    root = tk.Tk(); root.withdraw()
    app = Studio(root)
    errors = []
    root.report_callback_exception = lambda *args: errors.append(str(args))
    # Avoid a modal dialog blocking an unattended failed test.
    from . import app as app_module
    app_module.messagebox.showerror = lambda *args, **kw: errors.append(str(args))
    report = dict(status='FAIL', version=__version__, packaged=bool(getattr(__import__('sys'), 'frozen', False)), checks=[])
    def wait():
        deadline = time.monotonic() + 180
        while app.busy and time.monotonic() < deadline:
            root.update(); time.sleep(.01)
        root.update()
        rcof.require(not app.busy, 'GUI worker timed out')
        rcof.require(not errors, '; '.join(errors))
    def select(identifier):
        app.tree.selection_set(identifier); app.select(); root.update()
    try:
        app.open_path(sample); wait()
        session = app.session
        rcof.require(session is not None, 'GUI did not load sample')
        report['resources'] = len(session.resources)
        rcof.require(len(app.tree.get_children()) == len(session.resources), 'GUI rows differ from resource inventory')
        report['checks'].append('all resource rows populated')
        images = [next(x for x in session.container.resources if x['kind'] == 'png')]
        images += [x for x in session.container.resources if x['kind'] == 'dds']
        for item in images:
            select(item['id'])
            rcof.require(app.photo is not None, 'Tk image preview failed')
            report['checks'].append('preview ' + item['id'] + ' ' + item['kind'])
        app.filter.set('Unsupported'); app.populate()
        unsupported = [x for x in session.container.resources if not x['replacement_supported']]
        rcof.require(len(app.tree.get_children()) == len(unsupported), 'Unsupported filter count mismatch')
        if unsupported:
            select(unsupported[0]['id'])
            rcof.require(str(app.replace_button['state']) == 'disabled', 'Unsafe replacement button enabled')
            report['checks'].append('unsupported replacement disabled')
        app.filter.set('All formats'); app.populate(); select(images[0]['id'])
        app.submit('Test individual export', lambda: session.export_one(images[0]['id'], out / 'exports'), lambda _: None)
        wait(); report['checks'].append('individual export')
        app.submit('Test all exports', lambda: session.export_all(out / 'exports'), lambda x: report.update(export_all=x))
        wait(); report['checks'].append('all resources exported')
        app.submit('Test no-change reconstruction', lambda: session.rebuild(out / 'builds'), app.built)
        wait()
        rcof.require(session.last_report['byte_identical'], 'No-change GUI rebuild differs')
        report['no_change'] = session.last_report
        report['checks'].append('byte-identical rebuild and validation tab')
        modified = changed_png(session.payload(images[0]['id']))
        path = out / 'replacement.png'; rcof.write_new(path, modified)
        app.submit('Test staging', lambda: session.stage(images[0]['id'], path), app.staged); wait()
        rcof.require(len(session.pending) == 1, 'Staging failed')
        for item in images[1:]:
            payload = session.payload(item['id'])
            with Image.open(io.BytesIO(payload)) as image:
                image.load(); pixels = image.tobytes()
            modified_dds = None
            begin = item['image']['payload_offset']
            for index in range(begin + 1, min(begin + 32, len(payload))):
                candidate = bytearray(payload); candidate[index] ^= 1
                with Image.open(io.BytesIO(candidate)) as probe:
                    probe.load()
                    if probe.tobytes() != pixels:
                        modified_dds = bytes(candidate); break
            rcof.require(modified_dds is not None, 'No visible DDS mutation found')
            dds_path = out / (item['id'] + '.dds'); rcof.write_new(dds_path, modified_dds)
            app.submit('Test DDS staging', lambda i=item['id'], p=dds_path: session.stage(i, p), app.staged); wait()
            report['checks'].append('staged DDS ' + item['id'])
        app.submit('Test modified reconstruction', lambda: session.rebuild(out / 'builds'), app.built); wait()
        rcof.require(not session.last_report['byte_identical'], 'Replacement did not change output')
        report['replacement'] = session.last_report
        report['checks'].append('staged PNG/DDS rebuild')
        base = session.original_resources[images[0]['id']]
        original_png = session.original[base['offset']:base['offset'] + base['size']]
        bigger, smaller = size_change_probes(original_png)
        for label, payload in (('larger', bigger), ('smaller', smaller)):
            png_path = out / (label + '.png'); rcof.write_new(png_path, payload)
            app.submit('Test ' + label + ' PNG replacement', lambda p=png_path: session.stage(images[0]['id'], p), app.staged); wait()
            select(images[0]['id'])
            rcof.require(app.photo is not None, 'Relocated PNG preview failed')
            rcof.require(session.payload(images[0]['id']) == payload, 'Staged PNG does not match replacement')
            app.submit('Test relocated PNG rebuild', lambda: session.rebuild(out / 'builds'), app.built); wait()
            rcof.require(session.last_report['mode'] == 'png-relocation', 'Size change was not relocated')
            relocation = session.last_report['relocations'][0]
            rcof.require(relocation['new_size'] == len(payload) and relocation['new_offset'] % 16 == 0,
                         'Relocation size/alignment mismatch')
            rcof.require(session.last_report['untouched_contents_verified'], 'Untouched resource validation missing')
            report[label + '_png'] = session.last_report
            report['checks'].append(label + ' PNG relocation, preview, reopen and all-resource content verification')
        app.submit('Export relocated PNG', lambda: session.export_one(images[0]['id'], out / 'relocated-export'), lambda _: None)
        wait(); report['checks'].append('relocated PNG export')
        app.reset()
        # Complete ordinary-user extraction -> external editing -> GUI reimport
        # -> repack -> reopen -> re-extract acceptance, not merely API staging.
        app.submit('Extract editable project', lambda: session.export_project(out / 'editable'), app.project_exported); wait()
        folder = Path(app.last_project)
        app.submit('No-change extracted folder reimport', lambda: session.import_project(folder), app.imported); wait()
        rcof.require(session.working == session.original, 'No-change project import differs from original')
        report['checks'].append('byte-identical no-change extracted-folder round trip')
        (folder / base['file']).write_bytes(bigger)
        for item in images[1:]:
            (folder / item['file']).write_bytes((out / (item['id'] + '.dds')).read_bytes())
        nested_items = [x for x in session.container.resources if x['kind'] == 'rcsf']
        nested_edit = None
        if nested_items:
            from .nested import replace_string
            for item in nested_items:
                info = session.inspect_nested(item['id'])
                for text in info['strings']:
                    if not 0 < text['byte_length'] <= 40: continue
                    candidate = 'X' * (text['byte_length'] // 2)
                    if candidate == text['text']: continue
                    try: edited = replace_string(session.payload(item['id']), text['id'], candidate)
                    except ValueError: continue
                    (folder / item['file']).write_bytes(edited)
                    nested_edit = dict(resource=item['id'], string_id=text['id'], byte_length=text['byte_length'])
                    break
                if nested_edit: break
            rcof.require(nested_edit is not None, 'No safely editable nested string found')
            report['nested_edit'] = nested_edit
        app.submit('Scan external edits', lambda: session.scan_project(folder), app.scanned); wait()
        app.submit('Reimport external edits', lambda: session.import_project(folder), app.imported); wait()
        expected = dict(session.pending)
        rcof.require(len(expected) >= 3, 'Multiple external edits not detected')
        app.submit('Repack imported project', lambda: session.rebuild(out / 'workflow-builds'), app.built); wait()
        report['workflow_rebuild'] = session.last_report
        built_path = session.last_report['output']
        app.open_path(built_path); wait()
        reopened = app.session
        for item in session.container.resources:
            payload = expected.get(item['id'], session.original[item['offset']:item['offset'] + item['size']])
            rcof.require(reopened.payload(item['id']) == payload, 'Reopened workflow resource differs: ' + item['id'])
        select(images[0]['id']); rcof.require(app.photo is not None, 'Reopened replacement preview failed')
        app.submit('Re-extract rebuilt project', lambda: reopened.export_project(out / 'workflow-reextracted'), app.project_exported); wait()
        report['workflow'] = dict(status='PASS', edited_resources=sorted(expected), reopened_and_verified=len(session.resources),
                                  reextracted=app.last_project, no_change_project_identical=True)
        report['checks'].append('complete extracted-folder edit, reimport, repack, GUI reopen, every-payload verification and re-extraction')
        session.unchanged_source()
        report['checks'].append('reset and source identity')
        report.update(status='PASS', source_sha256=rcof.sha(session.original), errors=errors)
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        rcof.write_new(out / 'smoke.json', rcof.json_bytes(report))
        if not app.busy: root.destroy()
    return 0 if report['status'] == 'PASS' else 1
