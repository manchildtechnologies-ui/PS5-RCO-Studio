from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.experiments import inspect_rcsf, inspect_xml, relocate_png_append_only
from research.run_research import grow_png
from test_rcof import fixture, png, dds, r, set_u32


def rcsf_string_fixture(text='\U0001f600'):
    base = r.Container(fixture())
    tree = bytearray(base.table(0))
    encoded = text.encode('utf-16-le')
    struct.pack_into('<III', tree, 92, 4, 1, len(encoded))
    tables = [bytes(tree), base.table(1), b'', base.table(3), b'\0\0' + encoded + b'\0\0',
              b'', b'', b'', b'']
    result = bytearray(b'RCSF' + struct.pack('<I', 0x110) + bytes(72))
    for i, table in enumerate(tables):
        result += bytes((-len(result)) % 16)
        struct.pack_into('<II', result, 8 + i * 8, len(result), len(table))
        result += table
    return bytes(result)


class ExperimentalTests(unittest.TestCase):
    def test_append_relocation_grows_png(self):
        original = fixture()
        new, report = relocate_png_append_only(original, 'r00000', grow_png(png(2)))
        self.assertGreater(len(new), len(original))
        item = r.Container(new).resources[0]
        self.assertEqual(item['offset'] % 16, 0)
        self.assertEqual(new[item['offset']:item['offset'] + item['size']], grow_png(png(2)))
        self.assertTrue(report['reverse_metadata_and_truncate_identical'])

    def test_production_backend_still_rejects_growth(self):
        with self.assertRaises(ValueError): r.replace(fixture(), 'r00000', grow_png(png()))

    def test_relocation_rejects_same_size(self):
        with self.assertRaises(ValueError): relocate_png_append_only(fixture(), 'r00000', png(2))

    def test_relocation_rejects_dds(self):
        with self.assertRaises(ValueError): relocate_png_append_only(fixture(dds(), 'texture/dds'), 'r00000', dds() + b'0')

    def test_relocation_rejects_opaque(self):
        with self.assertRaises(ValueError): relocate_png_append_only(fixture(b'opaque', 'unknown'), 'r00000', b'longer payload')

    def test_relocation_rejects_filetable_not_eof(self):
        with self.assertRaises(ValueError): relocate_png_append_only(fixture() + b'trailer', 'r00000', grow_png(png()))

    def test_xml_inspection(self):
        result = inspect_xml(b'<root><info w="4" h="4"/><textures><texture u0="0" u1="1" v0="0" v1="1"/></textures></root>')
        self.assertEqual(result['atlas_entries'], 1)
        self.assertTrue(result['uv_ranges_valid'])
        self.assertFalse(result['editing_supported'])

    def test_xml_bad_uv_reported(self):
        result = inspect_xml(b'<root><textures><texture u0="2" u1="1" v0="0" v1="1"/></textures></root>')
        self.assertFalse(result['uv_ranges_valid'])

    def test_xml_entities_rejected(self):
        with self.assertRaises(ValueError): inspect_xml(b'<!DOCTYPE root [<!ENTITY a "boom">]><root>&a;</root>')

    def test_rcsf_magic_and_no_files_fixture(self):
        with self.assertRaises(ValueError): inspect_rcsf(fixture())
        # Generic RCSF normalization reuses validated tree links; unknown payload
        # interpretation remains explicit, and does not alter the input bytes.
        data = b'RCSF' + fixture()[4:]
        before = bytes(data)
        result = inspect_rcsf(data)
        self.assertEqual(data, before)
        self.assertEqual(result['nested_file_resources'], 1)
        self.assertFalse(result['editing_supported'])

    def test_rcsf_utf16_surrogate_code_unit_offset(self):
        result = inspect_rcsf(rcsf_string_fixture())
        value = result['strings'][0]
        self.assertEqual(value['text'], '\U0001f600')
        self.assertEqual(value['character_index'], 1)
        self.assertEqual(value['byte_length'], 4)

    def test_rcsf_odd_length_rejected(self):
        with self.assertRaises(ValueError): inspect_rcsf(set_u32(rcsf_string_fixture(), 180, 3))

    def test_rcsf_character_bounds_rejected(self):
        with self.assertRaises(ValueError): inspect_rcsf(set_u32(rcsf_string_fixture(), 176, r.NULL))

    def test_rcsf_terminator_rejected(self):
        data = bytearray(rcsf_string_fixture('A'))
        offset = struct.unpack_from('<I', data, 40)[0]
        data[offset + 4] = 1
        with self.assertRaises(ValueError): inspect_rcsf(bytes(data))


if __name__ == '__main__': unittest.main()
