import json
from pathlib import Path
import struct
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from test_rcof import fixture, png, dds, chunk, r
from test_studio import workspace
from studio.session import Session
from studio.app import Studio
from studio.replacement import compose, validate_rebuild, relocation_reason
from studio.smoke import size_change_probes


def larger(payload):
    return payload[:-12] + chunk(b'tEXt', b'Comment\0Larger PNG replacement regression') + payload[-12:]


def multi_fixture(entries):
    strings = bytearray(b'resource\0texture\0id\0type\0src\0')
    kinds = {}
    for _, kind in entries:
        if kind not in kinds:
            kinds[kind] = len(strings); strings += kind.encode() + b'\0'
    ids, files = bytearray(), bytearray()
    tree = bytearray(struct.pack('<7I', 0, 0, r.NULL, r.NULL, r.NULL, 28, 28 + 76 * (len(entries) - 1)))
    for index, (payload, kind) in enumerate(entries):
        node = 28 + 76 * index
        id_offset = len(ids); ids += struct.pack('<I', node) + f'image_{index}'.encode() + b'\0'
        ids += bytes((-len(ids)) % 4)
        files += bytes((-len(files)) % 16); file_offset = len(files); files += payload
        tree += struct.pack('<7I', 9, 3, 0, node - 76 if index else r.NULL,
                            node + 76 if index + 1 < len(entries) else r.NULL, r.NULL, r.NULL)
        tree += struct.pack('<4I', 17, 9, id_offset, 0)
        tree += struct.pack('<4I', 20, 3, kinds[kind], len(kind))
        tree += struct.pack('<4I', 25, 8, file_offset, len(payload))
    result = bytearray(b'RCOF' + struct.pack('<I', 0x110) + bytes(72))
    for i, data in enumerate((tree, ids, b'', strings, b'', b'', b'', b'', files)):
        result += bytes((-len(result)) % 16)
        struct.pack_into('<II', result, 8 + 8 * i, len(result), len(data)); result += data
    return bytes(result)


class RelocationTests(unittest.TestCase):
    def setUp(self):
        self.work = workspace()

    def session(self, payload=png()):
        path = self.work / 'original.rco'; path.write_bytes(fixture(payload))
        return Session(path)

    def stage(self, session, payload, ident='r00000'):
        path = self.work / 'replacement.png'; path.write_bytes(payload)
        return session.stage(ident, path)

    def test_larger_png_stages_and_rebuilds(self):
        session = self.session(); payload = larger(png(2))
        staged = self.stage(session, payload)
        self.assertEqual(staged['mode'], 'png-relocation')
        report = session.rebuild(self.work / 'outputs')
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['mode'], 'png-relocation')
        self.assertTrue(report['untouched_contents_verified'])
        item = r.Container(Path(report['output']).read_bytes()).resources[0]
        self.assertEqual(item['size'], len(payload)); self.assertEqual(item['offset'] % 16, 0)
        self.assertEqual(session.payload('r00000'), payload)
        self.assertEqual(session.source.read_bytes(), fixture())

    def test_larger_and_smaller_idat_streams_without_added_metadata(self):
        # A slightly larger RGBA fixture admits both re-encoding directions.
        import zlib
        ihdr = struct.pack('>IIBBBBB', 4, 4, 8, 6, 0, 0, 0)
        raw = bytes([0, 1, 2, 3, 255] + [0] * 12) * 4
        payload = r.PNG + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')
        # The production smoke mutation search is sample-specific. Test direct
        # IDAT recompression independently with matching decoded geometry.
        low_compression = r.PNG + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(raw, 0)) + chunk(b'IEND', b'')
        compact = r.PNG + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(bytes(68), 9)) + chunk(b'IEND', b'')
        self.assertLess(len(compact), len(payload)); self.assertGreater(len(low_compression), len(payload))
        for replacement in (low_compression, compact):
            result, after, _ = compose(fixture(payload), {'r00000': replacement})
            item = after.resources[0]
            self.assertEqual(result[item['offset']:item['offset'] + item['size']], replacement)

    def test_smaller_png_stages_and_rebuilds(self):
        session = self.session(larger(png()))
        self.stage(session, png(2)); report = session.rebuild(self.work / 'outputs')
        self.assertEqual(report['relocations'][0]['new_size'], len(png(2)))
        self.assertLess(report['relocations'][0]['new_size'], report['relocations'][0]['old_size'])
        self.assertEqual(session.payload('r00000'), png(2))
        self.assertTrue(report['replacement_contents_verified'])

    def test_preview_export_and_all_export_use_new_offsets(self):
        session = self.session(); payload = larger(png(2)); self.stage(session, payload)
        self.assertEqual(session.preview('r00000').getpixel((0, 0)), (2, 2, 3, 255))
        self.assertEqual(session.export_one('r00000', self.work / 'exports').read_bytes(), payload)
        exported = session.export_all(self.work / 'all')
        self.assertEqual(r.repack(exported['directory']), session.working)

    def test_repeated_staging_does_not_accumulate_appends(self):
        session = self.session(); payload = larger(png(2))
        self.stage(session, payload); first = session.working
        self.stage(session, payload); self.assertEqual(first, session.working)
        self.stage(session, larger(larger(png(2)))); self.stage(session, payload)
        self.assertEqual(first, session.working)

    def test_restore_original_removes_relocation(self):
        session = self.session(); self.stage(session, larger(png(2))); self.stage(session, png())
        self.assertFalse(session.pending); self.assertEqual(session.working, session.original)
        self.assertEqual(session.resource('r00000')['offset'], session.original_resources['r00000']['offset'])

    def test_reset_removes_relocation(self):
        session = self.session(); self.stage(session, larger(png(2))); session.reset()
        self.assertEqual(session.working, session.original)
        self.assertIs(session.current_container, session.container)

    def test_return_to_original_length_uses_fixed_size_patch(self):
        session = self.session(); self.stage(session, larger(png(2))); staged = self.stage(session, png(2))
        self.assertEqual(staged['mode'], 'fixed-size-patch')
        self.assertEqual(len(session.working), len(session.original))

    def test_two_png_relocations_and_both_dds_encodings(self):
        original = multi_fixture([(png(), 'texture/png'), (larger(png()), 'texture/png'),
                                  (dds(), 'texture/dds'), (dds(True), 'texture/dds'), (png(), 'texture/png')])
        pending = {'r00001': png(2), 'r00000': larger(png(2)),
                   'r00002': dds()[:-1] + b'\1', 'r00003': dds(True)[:-1] + b'\1'}
        data, after, validation = compose(original, pending)
        before = r.Container(original)
        self.assertEqual(len(validation['relocations']), 2)
        self.assertTrue(validation['reference_updates_verified'])
        self.assertEqual(after.resources[-1]['offset'], before.resources[-1]['offset'])
        self.assertEqual(after.resources[-1]['sha256'], before.resources[-1]['sha256'])
        reversed_order = dict(reversed(list(pending.items())))
        self.assertEqual(compose(original, reversed_order)[0], data)

    def test_stage_unrelated_after_relocation_preserves_both(self):
        source = self.work / 'multi.rco'; source.write_bytes(multi_fixture([(png(), 'texture/png'), (png(), 'texture/png')]))
        session = Session(source)
        self.stage(session, larger(png(2)), 'r00000'); self.stage(session, png(2), 'r00001')
        self.assertEqual(session.payload('r00000'), larger(png(2)))
        self.assertEqual(session.payload('r00001'), png(2))
        self.assertEqual(session.rebuild(self.work / 'outputs')['changed_resources'], ['r00000', 'r00001'])

    def test_nonzero_alignment_padding(self):
        original = fixture(); result, _, validation = compose(original, {'r00000': larger(png())})
        start = validation['relocations'][0]['new_offset']
        self.assertGreater(start, len(original))
        self.assertEqual(result[len(original):start], bytes(start - len(original)))

    def test_trailing_data_rejected_with_explanation(self):
        session = self.session(); session.source.write_bytes(session.original + b'unknown trailer')
        session = Session(session.source)
        with self.assertRaisesRegex(ValueError, 'file table does not end at EOF'): self.stage(session, larger(png()))
        self.assertFalse(session.pending); self.assertEqual(session.working, session.original)

    def test_unverified_size_sensitive_attribute_blocks_relocation(self):
        base = r.Container(fixture())
        tree = bytearray(base.table(0)); struct.pack_into('<I', tree, 32, 4)
        strings = base.table(3)
        tree += struct.pack('<4I', len(strings), 1, len(png()), 0)
        tables = [bytes(tree), base.table(1), base.table(2), strings + b'origsize\0',
                  base.table(4), base.table(5), base.table(6), base.table(7), base.table(8)]
        original = bytearray(b'RCOF' + struct.pack('<I', 0x110) + bytes(72))
        for i, data in enumerate(tables):
            original += bytes((-len(original)) % 16)
            struct.pack_into('<II', original, 8 + i * 8, len(original), len(data)); original += data
        container = r.Container(bytes(original))
        self.assertTrue(container.resources[0]['replacement_supported'])
        self.assertIn('origsize', relocation_reason(container, container.resources[0]))
        with self.assertRaisesRegex(ValueError, 'unverified texture attribute'):
            compose(bytes(original), {'r00000': larger(png(2))})
        # Its verified equal-length workflow is still usable.
        self.assertEqual(compose(bytes(original), {'r00000': png(2)})[1].resources[0]['size'], len(png()))

    def test_variable_dds_rejected_explicitly(self):
        for dx10 in (False, True):
            with self.subTest(dx10=dx10), self.assertRaisesRegex(ValueError, 'Variable-size DDS'):
                compose(fixture(dds(dx10), 'texture/dds'), {'r00000': dds(dx10) + b'\0'})

    def test_invalid_png_leaves_previous_staging_unchanged(self):
        session = self.session(); self.stage(session, larger(png(2))); before = session.working
        with self.assertRaises(ValueError): self.stage(session, b'invalid PNG')
        self.assertEqual(session.working, before)

    def test_new_dimensions_rejected(self):
        data = bytearray(png()); ihdr = struct.pack('>IIBBBBB', 2, 1, 8, 6, 0, 0, 0)
        data[8:33] = chunk(b'IHDR', ihdr)
        with self.assertRaises(ValueError): compose(fixture(), {'r00000': bytes(data)})

    def test_output_size_limit_rejected(self):
        with patch('studio.replacement.r.MAX_FILE', len(fixture()) + 10):
            with self.assertRaises(ValueError): compose(fixture(), {'r00000': larger(png())})

    def test_untouched_content_corruption_rejected(self):
        original = multi_fixture([(png(), 'texture/png'), (png(), 'texture/png')])
        data, parsed, _ = compose(original, {'r00000': larger(png(2))})
        changed = bytearray(data)
        # Another valid PNG with compatible shape must still fail exact content verification.
        offset = parsed.resources[1]['offset']; changed[offset:offset + len(png())] = png(2)
        with self.assertRaisesRegex(ValueError, 'content mismatch'): validate_rebuild(original, bytes(changed), {'r00000': larger(png(2))})

    def test_relocated_payload_corruption_rejected(self):
        original = fixture(); data, parsed, _ = compose(original, {'r00000': larger(png(2))})
        changed = bytearray(data); changed[parsed.resources[0]['offset'] + 45] ^= 1
        with self.assertRaises(ValueError): validate_rebuild(original, bytes(changed), {'r00000': larger(png(2))})

    def test_modified_original_orphan_bytes_rejected(self):
        original = fixture(); data, _, _ = compose(original, {'r00000': larger(png(2))})
        changed = bytearray(data); changed[r.Container(original).resources[0]['offset']] ^= 1
        with self.assertRaisesRegex(ValueError, 'Untouched original'): validate_rebuild(original, bytes(changed), {'r00000': larger(png(2))})

    def test_rebuild_readback_corruption_emits_fail_report(self):
        session = self.session(); self.stage(session, larger(png(2)))
        write = r.write_new
        def corrupt(path, data):
            write(path, data)
            if Path(path).suffix == '.rco': Path(path).write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        with patch('studio.session.rcof.write_new', side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, 'readback'): session.rebuild(self.work / 'outputs')
        self.assertEqual(session.last_report['status'], 'FAIL')


class RelocationGuiTests(unittest.TestCase):
    def setUp(self):
        self.work = workspace(); self.source = self.work / 'original.rco'
        self.root = tk.Tk(); self.root.withdraw(); self.app = Studio(self.root)
        self.errors = []
        self.patch = patch('studio.app.messagebox.showerror', side_effect=lambda *a, **k: self.errors.append(a))
        self.patch.start()

    def tearDown(self):
        self.wait(); self.root.destroy(); self.patch.stop()

    def wait(self):
        deadline = time.monotonic() + 30
        while self.app.busy and time.monotonic() < deadline:
            self.root.update(); time.sleep(.01)
        self.root.update(); self.assertFalse(self.app.busy)

    def exercise(self, original, replacement):
        self.source.write_bytes(original); self.app.open_path(self.source); self.wait()
        self.app.tree.selection_set('r00000'); self.app.select()
        self.assertIn('relocation supported', self.app.capability.get())
        path = self.work / 'replacement.png'; path.write_bytes(replacement)
        with patch('studio.app.filedialog.askopenfilename', return_value=str(path)) as dialog:
            self.app.replace_button.invoke(); self.wait()
            self.assertIn('size changes supported', dialog.call_args.kwargs['title'])
        row = self.app.tree.item('r00000')['values']
        self.assertEqual(int(str(row[3]).replace(',', '')), len(replacement))
        self.assertEqual(int(row[2], 16), self.app.session.resource('r00000')['offset'])
        self.assertIsNotNone(self.app.photo)
        with patch.object(self.app, 'output_folder', return_value=str(self.work / 'outputs')):
            self.app.build_button.invoke(); self.wait()
        self.assertFalse(self.errors)
        report = self.app.session.last_report
        self.assertEqual(report['status'], 'PASS'); self.assertEqual(report['mode'], 'png-relocation')
        self.assertEqual(self.source.read_bytes(), original)

    def test_larger_png_via_replace_and_rebuild_buttons(self): self.exercise(fixture(), larger(png(2)))

    def test_smaller_png_via_replace_and_rebuild_buttons(self): self.exercise(fixture(larger(png())), png(2))

    def test_unsupported_relocation_is_explained(self):
        self.source.write_bytes(fixture() + b'trailer'); self.app.open_path(self.source); self.wait()
        self.app.tree.selection_set('r00000'); self.app.select()
        self.assertIn('Fixed-size replacement only', self.app.capability.get())
        self.assertIn('EOF', self.app.capability.get())


if __name__ == '__main__': unittest.main()
