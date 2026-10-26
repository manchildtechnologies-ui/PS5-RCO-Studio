import json
from pathlib import Path
import struct
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from test_rcof import png, dds, r
from test_png_relocation import multi_fixture, larger
from test_experiments import rcsf_string_fixture
from test_studio import workspace
from studio.session import Session
from studio.replacement import compose, validate_rebuild, relocation_reason
from studio.app import Studio


def shared_fixture(payload=None, kind='texture/png', count=2):
    payload = png() if payload is None else payload
    data = multi_fixture([(payload, kind)] * count + [(png(), 'texture/png')])
    before = r.Container(data)
    result = bytearray(data)
    first = before.resources[0]
    for item in before.resources[1:count]:
        struct.pack_into('<II', result, item['attribute_offset'] + 8, first['relative_offset'], first['size'])
    return bytes(result)


def intersecting_fixture(contained=False):
    data = multi_fixture([(bytes(range(48)), 'unknown'), (bytes(range(48)), 'unknown'), (png(), 'texture/png')])
    c = r.Container(data); result = bytearray(data)
    struct.pack_into('<II', result, c.resources[1]['attribute_offset'] + 8,
                     c.resources[0]['relative_offset'] + 16, 16 if contained else 48)
    return bytes(result)


class SharedResourceTests(unittest.TestCase):
    def test_shared_png_identical_range_is_explicit(self):
        c = r.Container(shared_fixture())
        self.assertEqual(len(c.alias_groups), 1)
        self.assertEqual(c.resources[0]['shared_with'], ['r00001'])
        self.assertEqual(c.resources[0]['offset'], c.resources[1]['offset'])
        self.assertFalse(c.read_only)

    def test_identical_bytes_at_distinct_offsets_are_not_aliases(self):
        c = r.Container(multi_fixture([(png(), 'texture/png'), (png(), 'texture/png')]))
        self.assertFalse(c.alias_groups)

    def test_shared_png_raw_extract_and_repack_identical(self):
        data = shared_fixture(); folder = workspace() / 'extracted'
        r.extract(data, folder)
        c = r.Container(data)
        for item in c.resources:
            self.assertEqual((folder / item['file']).read_bytes(), data[item['offset']:item['offset'] + item['size']])
        self.assertEqual(r.repack(folder), data)

    def test_shared_dds_raw_roundtrip(self):
        for dx10 in (False, True):
            with self.subTest(dx10=dx10):
                data = shared_fixture(dds(dx10), 'texture/dds'); out = workspace() / 'export'
                r.extract(data, out); self.assertEqual(r.repack(out), data)

    def test_shared_opaque_preserved_and_not_editable(self):
        data = shared_fixture(b'<svg/>', 'texture/svg')
        self.assertFalse(r.Container(data).resources[0]['replacement_supported'])
        self.assertEqual(compose(data, {})[0], data)
        with self.assertRaises(ValueError): compose(data, {'r00000': b'<svg/>'})

    def test_equal_size_png_edit_uses_copy_on_write(self):
        data = shared_fixture(); before = r.Container(data)
        output, after, report = compose(data, {'r00000': png(2)})
        self.assertTrue(report['relocations'][0]['copy_on_write'])
        self.assertEqual(after.resources[1]['offset'], before.resources[1]['offset'])
        self.assertEqual(after.resources[1]['sha256'], before.resources[1]['sha256'])
        self.assertNotEqual(after.resources[0]['offset'], before.resources[0]['offset'])
        self.assertEqual(output[after.resources[0]['offset']:after.resources[0]['offset'] + len(png(2))], png(2))
        self.assertEqual(output[before.resources[0]['offset']:before.resources[0]['offset'] + len(png())], png())

    def test_larger_and_smaller_shared_png(self):
        for old, new in ((png(), larger(png(2))), (larger(png()), png(2))):
            with self.subTest(size=len(new)):
                data = shared_fixture(old); output, after, report = compose(data, {'r00000': new})
                self.assertTrue(report['relocations'][0]['copy_on_write'])
                self.assertEqual(after.resources[1]['sha256'], r.sha(old))
                self.assertEqual(after.resources[0]['sha256'], r.sha(new))

    def test_shared_dxt5_and_bc7_fixed_size_copy_on_write(self):
        for dx10 in (False, True):
            with self.subTest(dx10=dx10):
                original = dds(dx10); replacement = original[:-1] + b'\1'
                data = shared_fixture(original, 'texture/dds')
                output, after, report = compose(data, {'r00001': replacement})
                self.assertTrue(report['relocations'][0]['copy_on_write'])
                self.assertEqual(after.resources[0]['sha256'], r.sha(original))
                self.assertEqual(after.resources[1]['sha256'], r.sha(replacement))

    def test_shared_dds_different_length_still_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Variable-size DDS'):
            compose(shared_fixture(dds(), 'texture/dds'), {'r00000': dds() + b'\0'})

    def test_all_shared_references_edited_independently(self):
        data = shared_fixture(count=3)
        edits = {'r00000': png(2), 'r00001': larger(png(3)), 'r00002': png(4)}
        output, after, report = compose(data, edits)
        self.assertEqual(len(report['relocations']), 3)
        self.assertEqual(len({x['new_offset'] for x in report['relocations']}), 3)
        for item in after.resources[:3]: self.assertEqual(item['sha256'], r.sha(edits[item['id']]))
        self.assertEqual(compose(data, dict(reversed(list(edits.items()))))[0], output)

    def test_edit_one_of_three_preserves_remaining_shared_group(self):
        data = shared_fixture(count=3); output, after, report = compose(data, {'r00000': png(2)})
        self.assertEqual(after.alias_groups[0]['resource_ids'], ['r00001', 'r00002'])
        self.assertTrue(report['shared_references_preserved'])

    def test_noop_shared_edit_does_not_relocate(self):
        data = shared_fixture()
        output, _, report = compose(data, {'r00000': png()})
        self.assertEqual(output, data); self.assertFalse(report['relocations'])

    def test_shared_edit_requires_file_table_at_eof(self):
        with self.assertRaisesRegex(ValueError, 'file table does not end at EOF'):
            compose(shared_fixture() + b'trailer', {'r00000': png(2)})

    def test_conflicting_shared_interpretations_block_edits(self):
        data = multi_fixture([(png(), 'texture/png'), (png(), 'other')])
        c = r.Container(data); result = bytearray(data)
        struct.pack_into('<II', result, c.resources[1]['attribute_offset'] + 8, c.resources[0]['relative_offset'], c.resources[0]['size'])
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            compose(bytes(result), {'r00000': png(2)})
        self.assertEqual(compose(bytes(result), {})[0], bytes(result))

    def test_legacy_in_place_replacement_cannot_mutate_alias(self):
        with self.assertRaisesRegex(ValueError, 'copy-on-write'): r.replace(shared_fixture(), 'r00000', png(2))

    def test_partial_overlap_is_rejected_by_writer(self):
        with self.assertRaisesRegex(ValueError, 'partial-overlap'): compose(intersecting_fixture(), {})

    def test_contained_range_is_not_assumed_to_be_nested_format(self):
        with self.assertRaisesRegex(ValueError, 'contained-range-unverified'): r.Container(intersecting_fixture(True))

    def test_equal_start_different_lengths_are_containment_not_aliases(self):
        data = multi_fixture([(bytes(48), 'unknown'), (bytes(16), 'unknown')])
        c = r.Container(data); result = bytearray(data)
        struct.pack_into('<I', result, c.resources[1]['attribute_offset'] + 8, c.resources[0]['relative_offset'])
        with self.assertRaisesRegex(ValueError, 'contained-range-unverified'): r.Container(bytes(result))

    def test_partial_read_only_enumeration_and_raw_extraction(self):
        data = intersecting_fixture(); c = r.Container(data, read_only_overlaps=True)
        self.assertTrue(c.read_only); self.assertEqual(len(c.resources), 3)
        out = workspace() / 'read-only'; r.extract(data, out, read_only_overlaps=True)
        for item in c.resources:
            self.assertEqual((out / item['file']).read_bytes(), data[item['offset']:item['offset'] + item['size']])
        with self.assertRaisesRegex(ValueError, 'Read-only'): r.repack(out)

    def test_invalid_file_reference_is_never_read_only_salvaged(self):
        data = bytearray(shared_fixture()); c = r.Container(bytes(data))
        struct.pack_into('<I', data, c.resources[0]['attribute_offset'] + 8, 0xFFFFFFFF)
        with self.assertRaisesRegex(ValueError, 'invalid file reference'):
            r.Container(bytes(data), read_only_overlaps=True)

    def test_invalid_table_overlap_is_never_salvaged(self):
        data = bytearray(shared_fixture()); struct.pack_into('<I', data, 16, 80)
        with self.assertRaisesRegex(ValueError, 'tables'): r.Container(bytes(data), read_only_overlaps=True)

    def test_zero_length_ranges_do_not_claim_shared_bytes(self):
        data = multi_fixture([(png(), 'texture/png'), (b'', 'unknown')]); c = r.Container(data)
        result = bytearray(data); struct.pack_into('<I', result, c.resources[1]['attribute_offset'] + 8, c.resources[0]['relative_offset'] + 1)
        self.assertFalse(r.Container(bytes(result)).alias_groups)

    def test_nested_rcsf_is_separate_from_top_level_overlaps(self):
        c = r.Container(multi_fixture([(rcsf_string_fixture('AB'), 'unknown')]))
        self.assertEqual(c.resources[0]['kind'], 'rcsf'); self.assertFalse(c.range_issues)

    def test_shared_rcsf_edit_is_blocked_without_cow_schema(self):
        work = workspace(); source = work / 'nested.rco'; source.write_bytes(shared_fixture(rcsf_string_fixture('AB'), 'unknown'))
        session = Session(source)
        with self.assertRaises(ValueError): session.stage_string('r00000', 'test', 'CD')
        self.assertFalse(session.pending)

    def test_corrupted_untouched_alias_reference_rejected(self):
        original = shared_fixture(); output, after, _ = compose(original, {'r00000': png(2)})
        result = bytearray(output)
        struct.pack_into('<II', result, after.resources[1]['attribute_offset'] + 8, after.resources[0]['relative_offset'], after.resources[0]['size'])
        with self.assertRaises(ValueError): validate_rebuild(original, bytes(result), {'r00000': png(2)})

    def test_shared_extracted_copy_tampering_rejected(self):
        original = shared_fixture(); folder = workspace() / 'export'; r.extract(original, folder)
        manifest = json.loads((folder / 'manifest.json').read_text())
        (folder / manifest['resources'][1]['file']).write_bytes(png(2))
        with self.assertRaises(ValueError): r.repack(folder)


class SharedSessionTests(unittest.TestCase):
    def setUp(self):
        self.work = workspace(); self.source = self.work / 'shared.rco'; self.source.write_bytes(shared_fixture())
        self.session = Session(self.source)

    def test_session_preview_export_and_rebuild_after_cow(self):
        path = self.work / 'new.png'; path.write_bytes(png(2))
        report = self.session.stage('r00000', path)
        self.assertEqual(report['mode'], 'shared-copy-on-write')
        self.assertEqual(self.session.preview('r00000').getpixel((0, 0))[0], 2)
        self.assertEqual(self.session.preview('r00001').getpixel((0, 0))[0], 1)
        exported = self.session.export_one('r00000', self.work / 'out')
        self.assertEqual(exported.read_bytes(), png(2))
        built = self.session.rebuild(self.work / 'out')
        self.assertEqual(built['mode'], 'shared-copy-on-write')
        reopened = Session(built['output'])
        self.assertEqual(reopened.payload('r00001'), png())
        self.assertEqual(self.source.read_bytes(), shared_fixture())

    def test_shared_project_external_edits_and_repeated_stage(self):
        root = Path(self.session.export_project(self.work / 'out')['directory'])
        item = self.session.resource('r00000'); (root / item['file']).write_bytes(larger(png(2)))
        self.session.import_project(root); output = self.session.working
        self.session.import_project(root); self.assertEqual(self.session.working, output)
        self.assertEqual(self.session.payload('r00001'), png())
        self.session.reset(); self.assertEqual(self.session.working, self.session.original)

    def test_shared_no_change_project_preserves_aliases(self):
        root = self.session.export_project(self.work / 'out')['directory']
        self.session.import_project(root)
        self.assertEqual(self.session.working, self.session.original)
        self.assertEqual(len(self.session.current_container.alias_groups), 1)

    def test_partial_session_is_read_only_and_extractable(self):
        self.source.write_bytes(intersecting_fixture()); session = Session(self.source)
        self.assertTrue(session.container.read_only)
        session.export_one('r00000', self.work / 'one')
        folder = session.export_project(self.work / 'all')['directory']
        self.assertEqual(session.scan_project(folder)['status'], 'READ_ONLY')
        with self.assertRaises(ValueError): session.rebuild(self.work / 'build')
        with self.assertRaises(ValueError): session.import_project(folder)


class SharedGuiTests(unittest.TestCase):
    def setUp(self):
        self.work = workspace(); self.source = self.work / 'shared.rco'; self.source.write_bytes(shared_fixture())
        self.root = tk.Tk(); self.root.withdraw(); self.app = Studio(self.root)
        self.errors = []; self.patch = patch('studio.app.messagebox.showerror', side_effect=lambda *a, **k: self.errors.append(a)); self.patch.start()

    def wait(self):
        deadline = time.monotonic() + 30
        while self.app.busy and time.monotonic() < deadline: self.root.update(); time.sleep(.01)
        self.root.update(); self.assertFalse(self.app.busy)

    def tearDown(self): self.wait(); self.root.destroy(); self.patch.stop()

    def load(self):
        self.app.open_path(self.source); self.wait(); self.app.tree.selection_set('r00000'); self.app.select()

    def test_shared_png_gui_replacement_preserves_sibling(self):
        self.load(); self.assertIn('shared with', self.app.capability.get().lower())
        path = self.work / 'replacement.png'; path.write_bytes(png(2))
        with patch('studio.app.filedialog.askopenfilename', return_value=str(path)):
            self.app.replace_button.invoke(); self.wait()
        self.assertFalse(self.errors); self.assertEqual(self.app.session.payload('r00001'), png())
        self.assertIn('shared-copy-on-write', self.app.status.get())

    def test_partial_gui_disables_writing_but_allows_export(self):
        self.source.write_bytes(intersecting_fixture()); self.load()
        self.assertEqual(str(self.app.build_button['state']), 'disabled')
        self.assertEqual(str(self.app.replace_button['state']), 'disabled')
        self.assertEqual(str(self.app.all_button['state']), 'normal')
        self.assertEqual(str(self.app.export_button['state']), 'normal')

    def test_shared_dds_gui_explains_fixed_size_cow(self):
        self.source.write_bytes(shared_fixture(dds(True), 'texture/dds')); self.load()
        self.assertIn('Shared DDS', self.app.capability.get())
        self.assertEqual(str(self.app.replace_button['state']), 'normal')


if __name__ == '__main__': unittest.main()
