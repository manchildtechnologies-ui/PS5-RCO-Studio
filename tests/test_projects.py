import json
from pathlib import Path
import struct
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from test_rcof import fixture, png, dds, r
from test_studio import workspace
from test_png_relocation import larger, multi_fixture
from test_experiments import rcsf_string_fixture
from studio.session import Session
from studio import project, nested
from studio.app import Studio


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.work = workspace(); self.source = self.work / 'original.rco'
        self.source.write_bytes(multi_fixture([(png(), 'texture/png'), (png(), 'texture/png'), (dds(), 'texture/dds')]))
        self.session = Session(self.source)
        self.root = Path(self.session.export_project(self.work / 'outputs')['directory'])

    def resource_file(self, index=0):
        return self.root / self.session.container.resources[index]['file']

    def test_no_change_project_reimport_byte_identical(self):
        report = self.session.scan_project(self.root)
        self.assertEqual(report['status'], 'READY'); self.assertEqual(len(report['unchanged']), 3)
        self.session.import_project(self.root)
        self.assertEqual(self.session.working, self.source.read_bytes())
        self.assertTrue(self.session.rebuild(self.work / 'rebuild')['byte_identical'])

    def test_external_multiple_image_edits(self):
        self.resource_file(0).write_bytes(larger(png(2)))
        self.resource_file(1).write_bytes(png(2))
        self.resource_file(2).write_bytes(dds()[:-1] + b'\1')
        report = self.session.scan_project(self.root)
        self.assertEqual(len(report['modified']), 3)
        self.session.import_project(self.root)
        built = self.session.rebuild(self.work / 'builds')
        reopened = Session(built['output'])
        self.assertEqual(reopened.payload('r00000'), larger(png(2)))
        self.assertEqual(reopened.payload('r00001'), png(2))
        self.assertEqual(reopened.payload('r00002'), dds()[:-1] + b'\1')
        exported = reopened.export_project(self.work / 'again')
        reimport = Session.open_project(exported['directory']); reimport.import_project(exported['directory'])
        self.assertEqual(reimport.working, reopened.original)

    def test_missing_resource_blocks_without_state_change(self):
        path = self.resource_file(); path.rename(path.with_suffix('.missing'))
        report = self.session.scan_project(self.root)
        self.assertEqual(len(report['missing']), 1); self.assertEqual(len(report['additional']), 1)
        with self.assertRaisesRegex(ValueError, 'missing or additional'): self.session.import_project(self.root)
        self.assertFalse(self.session.pending)

    def test_additional_resource_blocks(self):
        (self.root / 'extra.png').write_bytes(png())
        self.assertEqual(self.session.scan_project(self.root)['additional'], ['extra.png'])
        with self.assertRaises(ValueError): self.session.import_project(self.root)

    def test_manifest_path_tampering_rejected(self):
        path = self.root / 'manifest.json'; data = json.loads(path.read_text())
        data['resources'][0]['file'] = '../original.rco'; path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'Manifest changed'): self.session.import_project(self.root)

    def test_manifest_offset_tampering_rejected(self):
        path = self.root / 'manifest.json'; data = json.loads(path.read_text())
        data['resources'][0]['offset'] += 16; path.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.session.import_project(self.root)

    def test_layout_tampering_rejected(self):
        path = self.root / 'layout.bin'; data = bytearray(path.read_bytes()); data[-1] ^= 1; path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'layout changed'): self.session.import_project(self.root)

    def test_baseline_tampering_rejected(self):
        path = self.root / 'baseline.rco'; path.write_bytes(fixture())
        with self.assertRaises(ValueError): self.session.import_project(self.root)

    def test_project_json_tampering_rejected(self):
        path = self.root / 'project.json'; data = json.loads(path.read_text()); data['schema'] = 'other'
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.session.import_project(self.root)

    def test_edited_unsupported_resource_rejected(self):
        source = self.work / 'opaque.rco'; source.write_bytes(fixture(b'opaque', 'unknown'))
        session = Session(source); folder = Path(session.export_project(self.work / 'opaque-out')['directory'])
        (folder / session.resource('r00000')['file']).write_bytes(b'edited')
        with self.assertRaises(ValueError): session.import_project(folder)
        self.assertEqual(session.working, session.original)

    def test_incompatible_image_edit_rolls_back_whole_import(self):
        self.resource_file(0).write_bytes(larger(png(2))); self.resource_file(2).write_bytes(b'invalid')
        with self.assertRaises(ValueError): self.session.import_project(self.root)
        self.assertFalse(self.session.pending)

    def test_import_replaces_pending_from_complete_folder(self):
        replacement = self.work / 'image.png'; replacement.write_bytes(png(2)); self.session.stage('r00000', replacement)
        self.session.import_project(self.root)
        self.assertFalse(self.session.pending); self.assertEqual(self.session.working, self.session.original)

    def test_export_includes_staged_edits_and_recovery_original(self):
        replacement = self.work / 'image.png'; replacement.write_bytes(larger(png(2))); self.session.stage('r00000', replacement)
        folder = Path(self.session.export_project(self.work / 'staged')['directory'])
        opened = Session.open_project(folder); opened.import_project(folder)
        self.assertEqual(opened.working, self.session.working)
        self.assertEqual((folder / 'baseline.rco').read_bytes(), self.session.original)

    def test_foreign_project_rejected(self):
        source = self.work / 'other.rco'; source.write_bytes(fixture())
        with self.assertRaisesRegex(ValueError, 'different original'): Session(source).import_project(self.root)

    def test_batch_replacements_atomic(self):
        a = self.work / 'a.png'; a.write_bytes(larger(png(2)))
        b = self.work / 'b.png'; b.write_bytes(b'bad')
        with self.assertRaises(ValueError): self.session.stage_multiple({'r00000': a, 'r00001': b})
        self.assertFalse(self.session.pending)
        b.write_bytes(png(2)); self.assertEqual(self.session.stage_multiple({'r00000': a, 'r00001': b})['staged'], 2)

    def test_hierarchy_recovery(self):
        self.assertEqual(self.session.hierarchy('r00000'), 'resource/image_0/src')

    def test_validate_current_content(self):
        self.assertEqual(self.session.validate()['resource_count'], 3)

    def test_progress_notifications(self):
        values = []; self.session.scan_project(self.root, lambda a, b: values.append((a, b)))
        self.assertTrue(values); self.assertEqual(values[0], (1, 3))

    def test_save_as_exact_name_and_no_overwrite(self):
        target = self.work / 'saved' / 'chosen.rco'
        report = self.session.save_as(target)
        self.assertEqual(Path(report['output']), target)
        self.assertTrue(target.with_name('chosen.rco.validation.json').exists())
        with self.assertRaises(ValueError): self.session.save_as(target)


class NestedEditingTests(unittest.TestCase):
    def setUp(self): self.original = rcsf_string_fixture('AB')

    def test_nested_string_no_change_identity(self):
        self.assertEqual(nested.replace_string(self.original, 'test', 'AB'), self.original)

    def test_same_utf16_length_edit_preserves_metadata(self):
        result = nested.replace_string(self.original, 'test', 'CD')
        self.assertEqual(nested.inspect(result, 'rcsf')['strings'][0]['text'], 'CD')
        self.assertTrue(nested.validate_rcsf(self.original, result)['offsets_and_unknown_metadata_preserved'])

    def test_surrogate_pair_edit(self):
        result = nested.replace_string(self.original, 'test', '\U0001f600')
        self.assertEqual(nested.inspect(result, 'rcsf')['strings'][0]['text'], '\U0001f600')

    def test_unequal_length_rejected(self):
        with self.assertRaisesRegex(ValueError, 'UTF-16 byte length'): nested.replace_string(self.original, 'test', 'ABC')

    def test_null_rejected(self):
        with self.assertRaises(ValueError): nested.replace_string(self.original, 'test', 'A\0')

    def test_metadata_modification_rejected(self):
        data = bytearray(self.original); data[6] ^= 1
        with self.assertRaises(ValueError): nested.validate_rcsf(self.original, bytes(data))

    def test_external_embedded_null_rejected(self):
        data = bytearray(self.original)
        start = struct.unpack_from('<I', data, 40)[0] + 2
        data[start:start + 2] = b'\0\0'
        with self.assertRaisesRegex(ValueError, 'embedded NUL'): nested.validate_rcsf(self.original, bytes(data))

    def test_nested_extract_and_inspect(self):
        target = workspace() / 'nested'; result = nested.export(self.original, 'rcsf', target)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual((target / 'original.rcsf').read_bytes(), self.original)

    def test_parent_rebuild_and_project_reimport(self):
        work = workspace(); source = work / 'nested.rco'; source.write_bytes(fixture(self.original, 'unknown'))
        session = Session(source); session.stage_string('r00000', 'test', 'CD')
        report = session.rebuild(work / 'builds')
        reopened = Session(report['output'])
        self.assertEqual(reopened.inspect_nested('r00000')['strings'][0]['text'], 'CD')
        folder = session.export_project(work / 'project')['directory']
        imported = Session.open_project(folder); imported.import_project(folder)
        self.assertEqual(imported.working, session.working)

    def test_shared_character_storage_edit_rejected(self):
        base = r.Container(multi_fixture([(png(), 'texture/png'), (png(), 'texture/png')]))
        tree = bytearray(base.table(0))
        for start in (92, 168): struct.pack_into('<III', tree, start, 4, 0, 4)
        tables = [bytes(tree), base.table(1), b'', base.table(3), 'AB\0'.encode('utf-16-le'), b'', b'', b'', b'']
        data = bytearray(b'RCSF' + struct.pack('<I', 0x110) + bytes(72))
        for index, table in enumerate(tables):
            data += bytes((-len(data)) % 16)
            struct.pack_into('<II', data, 8 + index * 8, len(data), len(table)); data += table
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            nested.replace_string(bytes(data), 'image_0', 'CD')


class ProjectGuiTests(unittest.TestCase):
    def setUp(self):
        self.work = workspace(); self.source = self.work / 'source.rco'; self.source.write_bytes(fixture())
        self.root = tk.Tk(); self.root.withdraw(); self.app = Studio(self.root); self.errors = []
        self.patch = patch('studio.app.messagebox.showerror', side_effect=lambda *a, **k: self.errors.append(a)); self.patch.start()
        self.app.open_path(self.source); self.wait()

    def tearDown(self): self.wait(); self.root.destroy(); self.patch.stop()

    def wait(self):
        deadline = time.monotonic() + 40
        while self.app.busy and time.monotonic() < deadline: self.root.update(); time.sleep(.01)
        self.root.update(); self.assertFalse(self.app.busy)

    def project(self): return self.app.session.export_project(self.work / 'projects')['directory']

    def test_project_export_button_and_reimport(self):
        with patch.object(self.app, 'output_folder', return_value=str(self.work / 'projects')):
            self.app.all_button.invoke(); self.wait()
        folder = self.app.last_project
        item = self.app.session.resource('r00000'); (Path(folder) / item['file']).write_bytes(larger(png(2)))
        with patch.object(self.app, 'edited_folder', return_value=folder):
            self.app.scan_button.invoke(); self.wait()
            self.assertIn('1 modified', self.app.status.get())
            self.app.import_button.invoke(); self.wait()
        self.assertTrue(self.app.session.pending); self.assertFalse(self.errors)

    def test_open_project_without_original(self):
        folder = self.project()
        with patch('studio.app.filedialog.askdirectory', return_value=folder):
            self.app.project_open_button.invoke(); self.wait()
        self.assertEqual(self.app.session.source.name, 'baseline.rco')

    def test_validate_button_logs(self):
        self.app.validate_button.invoke(); self.wait()
        self.assertIn('PASS', self.app.status.get()); self.assertIn('PASS', self.app.logs.get('1.0', 'end'))

    def test_hierarchy_selection_is_safe(self):
        self.app.hierarchical.set(True); self.app.populate(); self.root.update()
        self.app.tree.selection_set('node:0'); self.app.select()
        self.assertIn('resource', self.app.metadata.get('1.0', 'end'))
        self.assertEqual(str(self.app.replace_button['state']), 'disabled')

    def test_thumbnail_gallery_real_widgets(self):
        self.app.gallery_button.invoke(); self.wait()
        self.assertIn('Thumbnail', self.app.status.get()); self.assertFalse(self.errors)

    def test_original_and_replacement_comparison(self):
        path = self.work / 'replace.png'; path.write_bytes(png(2)); self.app.session.stage('r00000', path)
        self.app.tree.selection_set('r00000'); self.app.select()
        self.assertIsNotNone(self.app.original_image); self.assertIsNotNone(self.app.preview_image)

    def test_batch_button_uses_extracted_names(self):
        item = self.app.session.resource('r00000'); path = self.work / Path(item['file']).name; path.write_bytes(larger(png(2)))
        with patch('studio.app.filedialog.askopenfilenames', return_value=(str(path),)):
            self.app.batch_button.invoke(); self.wait()
        self.assertFalse(self.errors); self.assertTrue(self.app.session.pending)

    def test_nested_gui_editor(self):
        source = self.work / 'strings.rco'; source.write_bytes(fixture(rcsf_string_fixture('AB'), 'unknown'))
        self.app.open_path(source); self.wait(); self.app.tree.selection_set('r00000'); self.app.select()
        self.app.nested_button.invoke(); self.wait()
        self.app.nested_tree.selection_set('0'); self.app.nested_selected()
        self.app.nested_text.delete('1.0', 'end'); self.app.nested_text.insert('1.0', 'CD')
        self.app.nested_stage.invoke(); self.wait()
        self.assertFalse(self.errors); self.assertTrue(self.app.session.pending)

    def test_save_as_gui_button(self):
        target = self.work / 'save' / 'chosen.rco'
        with patch('studio.app.filedialog.asksaveasfilename', return_value=str(target)):
            self.app.save_button.invoke(); self.wait()
        self.assertFalse(self.errors); self.assertTrue(target.exists())

    def test_progress_footer_visible_at_default_geometry(self):
        self.root.deiconify(); self.root.update()
        bottom = self.root.winfo_rooty() + self.root.winfo_height()
        self.assertLess(self.app.progress.winfo_rooty() + self.app.progress.winfo_height(), bottom)
        self.root.withdraw()


class StressTests(unittest.TestCase):
    def test_64_mib_unknown_resource_preserved(self):
        original = fixture(bytes(64 * 1024 * 1024), 'unknown')
        container = r.Container(original)
        self.assertEqual(container.resources[0]['size'], 64 * 1024 * 1024)
        from studio.replacement import compose
        self.assertEqual(compose(original, {})[0], original)

    def test_corrupt_project_baseline_truncated(self):
        root = workspace() / 'project'; project.export_project(fixture(), {}, root)
        (root / 'baseline.rco').write_bytes(fixture()[:100])
        with self.assertRaises(ValueError): Session.open_project(root)

    def test_source_and_release_audit_rejects_samples(self):
        from source_bundle import audit_names
        for path in ('samples/original.rco', 'baseline.rco', 'data/a.rcsf', 'gimconv.exe', 'data/b.dds'):
            with self.assertRaises(ValueError): audit_names([path])

    def test_original_versus_replacement_memory_bounds(self):
        root = workspace(); source = root / 'preview.rco'; source.write_bytes(fixture())
        session = Session(source)
        with patch('studio.session.rcof.MAX_DECODE', 4):
            with self.assertRaisesRegex(ValueError, 'memory limit'): session.preview('r00000')


if __name__ == '__main__': unittest.main()
