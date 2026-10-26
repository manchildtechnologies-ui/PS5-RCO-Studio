import copy
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import uuid
import zlib

MODULE = Path(__file__).resolve().parents[1] / 'Rcomage' / 'rcof.py'
spec = importlib.util.spec_from_file_location('rcof', MODULE)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


@contextmanager
def test_directory():
    # Keep test evidence under the isolated workspace; no system-temp ACL changes.
    base = MODULE.parents[1] / 'test-work'
    base.mkdir(exist_ok=True)
    path = base / uuid.uuid4().hex
    path.mkdir()
    yield path


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & r.NULL)


def png(value=1):
    return (r.PNG + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes([0, value, 2, 3, 255]))) + chunk(b'IEND', b''))


def dds(dx10=False):
    v = [0] * 31
    v[0:7] = [124, 0x81007, 4, 4, 16, 0, 1]
    v[18:21] = [32, 4, struct.unpack('<I', b'DX10' if dx10 else b'DXT5')[0]]
    v[26] = 0x1000
    extra = struct.pack('<5I', 98, 3, 0, 1, 0) if dx10 else b''
    return b'DDS ' + struct.pack('<31I', *v) + extra + b'\x40' + bytes(15)


def fixture(payload=None, kind='texture/png', name='test'):
    payload = png() if payload is None else payload
    strings = b'resource\0texture\0id\0type\0src\0' + kind.encode() + b'\0'
    root = struct.pack('<7I', 0, 0, r.NULL, r.NULL, r.NULL, 28, 28)
    node = struct.pack('<7I', 9, 3, 0, r.NULL, r.NULL, r.NULL, r.NULL)
    node += struct.pack('<4I', 17, 9, 0, 0)
    node += struct.pack('<4I', 20, 3, 29, len(kind))
    node += struct.pack('<4I', 25, 8, 0, len(payload))
    tables = [root + node, struct.pack('<I', 28) + name.encode() + b'\0', b'', strings,
              b'', b'', b'', b'', payload]
    header = bytearray(b'RCOF' + struct.pack('<I', 0x110) + bytes(72))
    result = bytearray(header)
    for i, table in enumerate(tables):
        result += bytes((-len(result)) % 16)
        struct.pack_into('<II', result, 8 + i * 8, len(result), len(table))
        result += table
    return bytes(result)


def set_u32(data, offset, value):
    out = bytearray(data)
    struct.pack_into('<I', out, offset, value)
    return bytes(out)


class ParserTests(unittest.TestCase):
    def test_named_resource_and_offsets(self):
        c = r.Container(fixture())
        res = c.resources[0]
        self.assertEqual((res['name'], res['kind'], res['compression']), ('test', 'png', 'stored'))
        self.assertTrue(res['replacement_supported'])
        self.assertEqual(c.data[res['offset']:res['offset'] + res['size']], png())

    def test_bad_magic(self):
        with self.assertRaises(r.Invalid): r.Container(b'xxxx' + fixture()[4:])

    def test_unknown_version(self):
        with self.assertRaises(r.Invalid): r.Container(set_u32(fixture(), 4, 0x111))

    def test_every_truncation(self):
        data = fixture()
        for n in range(len(data)):
            with self.subTest(n=n), self.assertRaises(r.Invalid): r.Container(data[:n])

    def test_table_overlap(self):
        with self.assertRaises(r.Invalid): r.Container(set_u32(fixture(), 16, 80))

    def test_table_alignment(self):
        with self.assertRaises(r.Invalid): r.Container(set_u32(fixture(), 16, 185))

    def test_table_overflow(self):
        with self.assertRaises(r.Invalid): r.Container(set_u32(fixture(), 76, r.NULL))

    def test_huge_attribute_count(self):
        with self.assertRaises(r.Invalid): r.Container(set_u32(fixture(), 84, r.NULL))

    def test_dangling_link(self):
        with self.assertRaises(r.Invalid): r.Container(set_u32(fixture(), 100, 32))

    def test_tree_cycle(self):
        with self.assertRaises(r.Invalid): r.Container(set_u32(fixture(), 124, 28))

    def test_unreachable_node(self):
        data = set_u32(set_u32(fixture(), 100, r.NULL), 104, r.NULL)
        with self.assertRaises(r.Invalid): r.Container(data)

    def test_id_loopback(self):
        data = fixture()
        off = struct.unpack_from('<I', data, 16)[0]
        with self.assertRaises(r.Invalid): r.Container(set_u32(data, off, 0))

    def test_file_bounds(self):
        with self.assertRaises(r.Invalid): r.Container(set_u32(fixture(), 180, r.NULL))

    def test_string_bounds(self):
        with self.assertRaises(r.Invalid): r.Container(set_u32(fixture(), 168, r.NULL))

    def test_unknown_attribute_reported(self):
        c = r.Container(set_u32(fixture(), 140, 99))
        self.assertEqual(len(c.unsupported_attributes), 1)
        self.assertFalse(c.resources[0]['replacement_supported'])

    def test_unknown_payload_reported(self):
        c = r.Container(fixture(b'opaque', kind='unknown'))
        self.assertEqual(c.resources[0]['kind'], 'unknown')
        self.assertIn('unsupported', c.resources[0]['unsupported_reason'])

    def test_declared_type_mismatch(self):
        self.assertFalse(r.Container(fixture(kind='texture/dds')).resources[0]['replacement_supported'])

    def test_malicious_name_is_preserved_but_not_used_as_path(self):
        c = r.Container(fixture(name='../CON:bad/evil'))
        res = c.resources[0]
        self.assertEqual(res['name'], '../CON:bad/evil')
        self.assertEqual(Path(res['file']).parent.as_posix(), 'resources')


class ImageTests(unittest.TestCase):
    def test_png_decode(self):
        self.assertEqual(r.png_info(png())['width'], 1)

    def test_png_bad_crc(self):
        data = bytearray(png()); data[-1] ^= 1
        with self.assertRaises(r.Invalid): r.png_info(data)

    def test_png_trailing_bytes(self):
        with self.assertRaises(r.Invalid): r.png_info(png() + b'\0')

    def test_png_invalid_deflate(self):
        data = r.PNG + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
        data += chunk(b'IDAT', b'not zlib') + chunk(b'IEND', b'')
        with self.assertRaises(r.Invalid): r.png_info(data)

    def test_png_invalid_filter(self):
        data = r.PNG + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
        data += chunk(b'IDAT', zlib.compress(bytes([5, 1, 2, 3, 255]))) + chunk(b'IEND', b'')
        with self.assertRaises(r.Invalid): r.png_info(data)

    def test_dds_dxt5(self):
        self.assertEqual(r.dds_info(dds())['fourcc'], 'DXT5')

    def test_dds_bc7(self):
        self.assertEqual(r.dds_info(dds(True))['dx10'][0], 98)

    def test_dds_short_payload(self):
        with self.assertRaises(r.Invalid): r.dds_info(dds()[:-1])

    def test_dds_extra_payload(self):
        with self.assertRaises(r.Invalid): r.dds_info(dds() + b'x')

    def test_dds_unknown_format(self):
        with self.assertRaises(r.Invalid): r.dds_info(set_u32(dds(True), 128, 999))

    def test_dds_array(self):
        with self.assertRaises(r.Invalid): r.dds_info(set_u32(dds(True), 140, 2))

    def test_dds_cube(self):
        with self.assertRaises(r.Invalid): r.dds_info(set_u32(dds(), 112, 0x200))

    def test_dds_mip_overflow(self):
        with self.assertRaises(r.Invalid): r.dds_info(set_u32(dds(), 28, 100))


class RoundTripTests(unittest.TestCase):
    def test_reconstruct_every_byte(self):
        original = fixture()
        with test_directory() as tmp:
            out = Path(tmp) / 'extracted'
            r.extract(original, out)
            self.assertEqual(r.repack(out), original)
            self.assertNotEqual((out / 'layout.bin').read_bytes(), original)

    def test_opaque_roundtrip(self):
        original = fixture(b'RCSF opaque data', 'unknown')
        with test_directory() as tmp:
            out = Path(tmp) / 'extract'
            r.extract(original, out)
            self.assertEqual(r.repack(out), original)

    def test_repack_rejects_resource_tamper(self):
        with test_directory() as tmp:
            out = Path(tmp) / 'extract'; r.extract(fixture(), out)
            p = next((out / 'resources').iterdir()); p.write_bytes(b'bad')
            with self.assertRaises(r.Invalid): r.repack(out)

    def test_repack_rejects_layout_tamper(self):
        with test_directory() as tmp:
            out = Path(tmp) / 'extract'; r.extract(fixture(), out)
            (out / 'layout.bin').write_bytes(b'bad')
            with self.assertRaises(r.Invalid): r.repack(out)

    def test_repack_rejects_metadata_tamper(self):
        with test_directory() as tmp:
            out = Path(tmp) / 'extract'; r.extract(fixture(), out)
            path = out / 'manifest.json'; m = json.loads(path.read_text())
            m['resources'][0]['offset'] += 1; path.write_text(json.dumps(m))
            with self.assertRaises(r.Invalid): r.repack(out)

    def test_manifest_path_escape(self):
        with test_directory() as tmp:
            with self.assertRaises(r.Invalid): r.child_file(tmp, '../escape.bin')

    def test_extract_refuses_existing_directory(self):
        with test_directory() as tmp:
            with self.assertRaises(r.Invalid): r.extract(fixture(), tmp)

    def test_write_refuses_existing_file(self):
        with test_directory() as tmp:
            p = Path(tmp) / 'source'; p.write_bytes(b'original')
            with self.assertRaises(FileExistsError): r.write_new(p, b'changed')
            self.assertEqual(p.read_bytes(), b'original')

    def test_changed_png_replacement(self):
        original = fixture()
        replacement = png(2)
        self.assertEqual(len(replacement), len(png()))
        result, report = r.replace(original, 'r00000', replacement)
        self.assertNotEqual(result, original)
        self.assertTrue(report['non_target_bytes_identical'])
        res = r.Container(result).resources[0]
        self.assertEqual(result[res['offset']:res['offset'] + res['size']], replacement)

    def test_changed_dds_replacement(self):
        for dx10 in (False, True):
            with self.subTest(dx10=dx10):
                payload = dds(dx10); replacement = payload[:-1] + b'\x01'
                result, report = r.replace(fixture(payload, 'texture/dds'), 'r00000', replacement)
                self.assertGreater(report['changed_bytes'], 0)

    def test_noop_replacement(self):
        original = fixture()
        self.assertEqual(r.replace(original, 'r00000', png())[0], original)

    def test_replacement_size_rejected(self):
        with self.assertRaises(r.Invalid): r.replace(fixture(), 'r00000', png() + b'\0')

    def test_replacement_format_rejected(self):
        with self.assertRaises(r.Invalid): r.replace(fixture(), 'r00000', bytes(len(png())))

    def test_unknown_replacement_rejected(self):
        with self.assertRaises(r.Invalid): r.replace(fixture(b'opaque', 'unknown'), 'r00000', b'opaque')

    def test_unknown_resource_rejected(self):
        with self.assertRaises(r.Invalid): r.replace(fixture(), 'r99999', png())


if __name__ == '__main__':
    unittest.main()
