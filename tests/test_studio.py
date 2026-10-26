import io
import json
from pathlib import Path
import sys
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.session import Session
from studio.app import Studio
from test_rcof import fixture, png, dds, r


def workspace():
    path = Path(__file__).resolve().parents[1] / 'test-work' / ('studio-' + uuid.uuid4().hex)
    path.mkdir(parents=True)
    return path


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.root = workspace()
        self.source = self.root / 'source.rco'
        self.source.write_bytes(fixture())
        self.session = Session(self.source)
        self.outputs = self.root / 'outputs'

    def test_no_change_rebuild_and_report(self):
        report = self.session.rebuild(self.outputs)
        self.assertEqual(report['status'], 'PASS')
        self.assertTrue(report['byte_identical'])
        self.assertEqual(Path(report['output']).read_bytes(), self.source.read_bytes())
        self.assertEqual(json.loads((Path(report['output']).parent / 'validation.json').read_text()), report)

    def test_preview(self):
        self.assertEqual(self.session.preview('r00000').size, (1, 1))

    def test_stage_rebuild_export_reset(self):
        replacement = self.root / 'replace.png'; replacement.write_bytes(png(2))
        self.session.stage('r00000', replacement)
        self.assertEqual(len(self.session.pending), 1)
        target = self.session.export_one('r00000', self.outputs)
        self.assertEqual(target.read_bytes(), png(2))
        report = self.session.rebuild(self.outputs)
        self.assertFalse(report['byte_identical'])
        self.assertTrue(report['non_target_bytes_identical'])
        self.assertEqual(self.source.read_bytes(), fixture())
        self.session.reset()
        self.assertFalse(self.session.pending)
        self.assertEqual(self.session.working, self.session.original)

    def test_restore_original_unstages(self):
        replacement = self.root / 'replace.png'; replacement.write_bytes(png(2))
        self.session.stage('r00000', replacement)
        replacement.write_bytes(png())
        self.session.stage('r00000', replacement)
        self.assertFalse(self.session.pending)

    def test_export_all_lossless(self):
        result = self.session.export_all(self.outputs)
        self.assertEqual(r.repack(result['directory']), self.source.read_bytes())

    def test_source_folder_output_rejected(self):
        with self.assertRaises(ValueError): self.session.rebuild(self.source.parent)

    def test_individual_export_does_not_overwrite(self):
        target = self.session.export_one('r00000', self.outputs)
        before = target.read_bytes()
        with self.assertRaises(FileExistsError): self.session.export_one('r00000', self.outputs)
        self.assertEqual(before, target.read_bytes())

    def test_external_source_modification_rejected(self):
        self.source.write_bytes(fixture(png(2)))
        with self.assertRaises(ValueError): self.session.rebuild(self.outputs)

    def test_failed_replacement_preserves_session(self):
        bad = self.root / 'bad.png'; bad.write_bytes(b'bad')
        with self.assertRaises(ValueError): self.session.stage('r00000', bad)
        self.assertEqual(self.session.working, self.session.original)
        self.assertFalse(self.session.pending)

    def test_unsupported_exports_but_cannot_preview_or_replace(self):
        self.source.write_bytes(fixture(b'opaque', 'unknown'))
        session = Session(self.source)
        with self.assertRaises(ValueError): session.preview('r00000')
        bad = self.root / 'bad'; bad.write_bytes(b'opaque')
        with self.assertRaises(ValueError): session.stage('r00000', bad)
        self.assertEqual(session.export_one('r00000', self.outputs).read_bytes(), b'opaque')

    def test_multiple_rebuilds_use_distinct_directories(self):
        a = self.session.rebuild(self.outputs); b = self.session.rebuild(self.outputs)
        self.assertNotEqual(a['output'], b['output'])

    def test_dds_preview_and_replacement(self):
        for dx10 in (False, True):
            self.source.write_bytes(fixture(dds(dx10), 'texture/dds'))
            session = Session(self.source)
            self.assertEqual(session.preview('r00000').size, (4, 4))
            new = self.root / 'new.dds'; new.write_bytes(dds(dx10)[:-1] + b'\1')
            session.stage('r00000', new)
            self.assertTrue(session.rebuild(self.outputs)['original_unchanged'])


class GuiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.work = workspace()
        self.source = self.work / 'source.rco'; self.source.write_bytes(fixture())
        self.root = tk.Tk(); self.root.withdraw()
        self.app = Studio(self.root)
        self.errors = []
        self.error_patch = patch('studio.app.messagebox.showerror', side_effect=lambda *a, **kw: self.errors.append(a))
        self.error_patch.start()

    def tearDown(self):
        self.wait()
        self.error_patch.stop()
        self.root.destroy()

    def wait(self):
        deadline = time.monotonic() + 30
        while self.app.busy and time.monotonic() < deadline:
            self.root.update(); time.sleep(0.01)
        self.root.update()
        self.assertFalse(self.app.busy, 'GUI operation timed out')

    def load(self):
        self.app.open_path(self.source); self.wait()
        self.assertFalse(self.errors)

    def select_first(self):
        self.app.tree.selection_set('r00000'); self.app.select(); self.root.update()

    def test_async_open_populates_fields(self):
        self.load()
        row = self.app.tree.item('r00000')['values']
        self.assertEqual(row[0], 'r00000')
        self.assertIn('test', row[1]); self.assertTrue(row[2].startswith('0x'))
        self.assertEqual(row[4], 'PNG')

    def test_selection_preview_metadata_and_actions(self):
        self.load(); self.select_first()
        self.assertIsNotNone(self.app.photo)
        self.assertIn('attribute_offset', self.app.metadata.get('1.0', 'end'))
        self.assertEqual(str(self.app.replace_button['state']), 'normal')

    def test_filter_and_search(self):
        self.load()
        self.app.search.set('no matching entry')
        self.assertFalse(self.app.tree.get_children())
        self.app.search.set(''); self.app.filter.set('DDS'); self.app.populate()
        self.assertFalse(self.app.tree.get_children())
        self.app.filter.set('All formats'); self.app.populate()
        self.assertEqual(len(self.app.tree.get_children()), 1)

    def test_open_dialog_action(self):
        with patch('studio.app.filedialog.askopenfilename', return_value=str(self.source)):
            self.app.open_button.invoke(); self.wait()
        self.assertEqual(self.app.session.source, self.source.resolve())

    def test_stage_and_rebuild_buttons(self):
        self.load(); self.select_first()
        replacement = self.work / 'replace.png'; replacement.write_bytes(png(2))
        with patch('studio.app.filedialog.askopenfilename', return_value=str(replacement)):
            self.app.replace_button.invoke(); self.wait()
        self.assertEqual(self.app.tree.item('r00000')['values'][-1], 'Staged')
        with patch.object(self.app, 'output_folder', return_value=str(self.work / 'outputs')):
            self.app.build_button.invoke(); self.wait()
        self.assertEqual(self.app.session.last_report['status'], 'PASS')
        self.assertIn('PASS', self.app.status.get())
        self.assertEqual(self.source.read_bytes(), fixture())
        self.app.reset_button.invoke()
        self.assertFalse(self.app.session.pending)

    def test_exports_through_buttons(self):
        self.load(); self.select_first()
        with patch.object(self.app, 'output_folder', return_value=str(self.work / 'outputs')):
            self.app.export_button.invoke(); self.wait()
            self.app.all_button.invoke(); self.wait()
        self.assertEqual(len(list((self.work / 'outputs').glob('*.png'))), 1)
        self.assertEqual(len(list((self.work / 'outputs').glob('extracted-*'))), 1)

    def test_failed_open_keeps_session(self):
        self.load(); previous = self.app.session
        bad = self.work / 'invalid.rco'; bad.write_bytes(b'invalid')
        self.app.open_path(bad); self.wait()
        self.assertIs(self.app.session, previous)
        self.assertEqual(len(self.errors), 1)

    def test_unsupported_button_disabled(self):
        self.source.write_bytes(fixture(b'RCSF opaque', 'unknown'))
        self.load(); self.select_first()
        self.assertEqual(str(self.app.replace_button['state']), 'disabled')
        self.assertEqual(str(self.app.export_button['state']), 'normal')
        self.assertIn('Export only', self.app.capability.get())

    def test_busy_gates_and_recovers(self):
        self.app.open_path(self.source)
        self.assertEqual(str(self.app.open_button['state']), 'disabled')
        self.wait()
        self.assertEqual(str(self.app.open_button['state']), 'normal')

    def test_png_dds_real_tk_previews(self):
        for payload, kind in ((png(), 'texture/png'), (dds(), 'texture/dds'), (dds(True), 'texture/dds')):
            self.source.write_bytes(fixture(payload, kind)); self.load(); self.select_first()
            self.assertIsNotNone(self.app.photo)
            self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
