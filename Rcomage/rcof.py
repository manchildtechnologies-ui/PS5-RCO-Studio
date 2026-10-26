"""Offline, lossless RCOF 0x110 sidecar. No console or network operations.

The legacy executable and C source are deliberately not patched: RCOF is a
different container. Repacking reassembles stored resources and opaque layout;
replacement is restricted to equal-length, format-compatible PNG/BC DDS data.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys
import zlib

NULL = 0xFFFFFFFF
TABLE_NAMES = ('tree', 'id_strings', 'id_integers', 'strings', 'characters',
               'style_ids', 'integers', 'floats', 'files')
PNG = b'\x89PNG\r\n\x1a\n'
MAX_FILE = 512 * 1024 * 1024
MAX_DECODE = 256 * 1024 * 1024


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_file(path):
    p = Path(path)
    require(p.stat().st_size <= MAX_FILE, 'input exceeds 512 MiB limit')
    return p.read_bytes()


def region(data, offset, size, context):
    require(0 <= offset <= len(data) and 0 <= size <= len(data) - offset,
            f'{context}: out-of-bounds range {offset:#x}+{size:#x}')
    return data[offset:offset + size]


def cstring(data, offset):
    require(0 <= offset < len(data), 'string offset outside table')
    end = data.find(b'\0', offset)
    require(end >= 0, 'unterminated string')
    try:
        return data[offset:end].decode('utf-8')
    except UnicodeDecodeError as e:
        raise Invalid('invalid UTF-8 string') from e


def png_info(data):
    """Validate chunks, CRCs, image dimensions and the bounded IDAT stream.

    No pixel conversion. Ancillary chunks remain byte-for-byte unchanged.
    """
    require(data.startswith(PNG), 'PNG signature missing')
    p, chunks, idat, palette, ended_idat = 8, [], [], None, False
    info = None
    while p < len(data):
        head = region(data, p, 8, 'PNG chunk header')
        size, kind = struct.unpack('>I4s', head)
        require(all(65 <= c <= 90 or 97 <= c <= 122 for c in kind), 'invalid PNG chunk type')
        payload = region(data, p + 8, size, 'PNG chunk')
        crc = struct.unpack('>I', region(data, p + 8 + size, 4, 'PNG CRC'))[0]
        require(zlib.crc32(kind + payload) & NULL == crc, 'PNG CRC mismatch')
        require(kind in (b'IHDR', b'PLTE', b'IDAT', b'IEND') or kind[0] & 32,
                'unsupported critical PNG chunk')
        if not chunks:
            require(kind == b'IHDR' and size == 13, 'PNG must begin with IHDR')
            w, h, depth, color, comp, filt, interlace = struct.unpack('>IIBBBBB', payload)
            require(0 < w <= 32768 and 0 < h <= 32768, 'PNG dimensions outside supported bounds')
            require(color in (0, 2, 3, 4, 6), 'invalid PNG color type')
            allowed = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
            require(depth in allowed[color] and comp == filt == 0 and interlace in (0, 1),
                    'unsupported PNG IHDR')
            info = dict(width=w, height=h, bit_depth=depth, color_type=color, interlace=interlace)
        elif kind == b'IHDR':
            raise Invalid('duplicate PNG IHDR')
        if kind == b'PLTE':
            require(palette is None and not idat and size > 0 and size % 3 == 0 and size <= 768,
                    'invalid PNG palette')
            palette = payload
        if kind == b'IDAT':
            require(not ended_idat, 'nonconsecutive PNG IDAT')
            idat.append(payload)
        elif idat:
            ended_idat = True
        chunks.append(kind)
        p += size + 12
        if kind == b'IEND':
            require(size == 0 and p == len(data), 'PNG trailing data or nonempty IEND')
            break
    require(chunks and chunks[-1] == b'IEND' and idat, 'incomplete PNG')
    require(info['color_type'] != 3 or (palette is not None and len(palette) // 3 <= 1 << info['bit_depth']),
            'missing or oversized PNG palette')
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[info['color_type']]
    passes = [(0, 0, 1, 1)] if not info['interlace'] else [
        (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
        (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
    rows = []
    for x, y, dx, dy in passes:
        w = max(0, (info['width'] - x + dx - 1) // dx)
        h = max(0, (info['height'] - y + dy - 1) // dy)
        if w and h:
            rows.append((h, (w * channels * info['bit_depth'] + 7) // 8 + 1))
    expected = sum(h * stride for h, stride in rows)
    require(expected <= MAX_DECODE, 'PNG decoded data exceeds limit')
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(b''.join(idat), expected + 1)
    except zlib.error as e:
        raise Invalid(f'PNG IDAT zlib error: {e}') from e
    require(len(raw) == expected and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
            'PNG IDAT length/termination mismatch')
    p = 0
    for h, stride in rows:
        require(all(raw[p + r * stride] <= 4 for r in range(h)), 'invalid PNG scanline filter')
        p += h * stride
    return info


def dds_info(data):
    require(data.startswith(b'DDS ') and len(data) >= 128, 'DDS header missing')
    v = struct.unpack_from('<31I', data, 4)
    require(v[0] == 124 and v[18] == 32, 'invalid DDS header sizes')
    flags, h, w, linear, depth, mips = v[1:7]
    require(flags & 0x1007 == 0x1007 and v[19] == 4, 'DDS requires texture dimensions and FOURCC')
    require(v[26] & 0x1000 and v[27] == 0 and depth in (0, 1), 'unsupported DDS cube/volume/caps')
    require(0 < w <= 32768 and 0 < h <= 32768, 'DDS dimensions outside supported bounds')
    require(not (flags & 0x20000) or mips > 0, 'DDS mip flag without mip count')
    require(flags & 0x20000 or mips in (0, 1), 'DDS mip count without mip flag')
    levels = max(1, mips)
    require(levels <= max(w, h).bit_length(), 'DDS mip count invalid')
    fourcc = data[84:88]
    offset, dx10 = 128, None
    if fourcc == b'DXT1':
        block = 8
    elif fourcc in (b'DXT3', b'DXT5'):
        block = 16
    elif fourcc == b'DX10':
        dx10 = list(struct.unpack('<5I', region(data, 128, 20, 'DDS DX10')))
        fmt, dim, misc, array, misc2 = dx10
        require(dim == 3 and misc == 0 and array == 1 and misc2 <= 4, 'unsupported DDS DX10 layout')
        require(fmt in (71, 72, 74, 75, 77, 78, 80, 81, 83, 84, 95, 96, 98, 99),
                f'unsupported DDS DXGI format {fmt}')
        block = 8 if fmt in (71, 72, 80, 81) else 16
        offset = 148
    else:
        raise Invalid(f'unsupported DDS FOURCC {fourcc!r}')
    expected = sum(max(1, ((w >> i) + 3) // 4) * max(1, ((h >> i) + 3) // 4) * block
                   for i in range(levels))
    require(len(data) == offset + expected, 'DDS block payload length mismatch')
    if flags & 0x80000:
        require(linear == max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block,
                'DDS linear size mismatch')
    return dict(width=w, height=h, levels=levels, fourcc=fourcc.decode('ascii'), dx10=dx10,
                block_bytes=block, header_sha256=sha(data[:offset]), payload_offset=offset)


def identify(data):
    if data.startswith(PNG):
        kind, validator = 'png', png_info
    elif data.startswith(b'DDS '):
        kind, validator = 'dds', dds_info
    else:
        kind = 'rcsf' if data.startswith(b'RCSF') else 'xml' if data.startswith(b'<') else 'unknown'
        return kind, None, 'opaque extraction only; replacement unsupported'
    try:
        return kind, validator(data), None
    except Invalid as e:
        return kind, None, str(e)


class Container:
    def __init__(self, data, *, read_only_overlaps=False):
        require(len(data) <= MAX_FILE, 'container exceeds size limit')
        require(len(data) >= 80 and data[:4] == b'RCOF', 'unsupported magic (expected RCOF)')
        require(struct.unpack_from('<I', data, 4)[0] == 0x110, 'unsupported RCOF version')
        self.data = data
        self.tables = []
        for i, name in enumerate(TABLE_NAMES):
            off, size = struct.unpack_from('<II', data, 8 + i * 8)
            region(data, off, size, name)
            require(off >= 80 and off % 16 == 0, f'{name}: unsupported table alignment')
            self.tables.append(dict(name=name, offset=off, size=size,
                                    sha256=sha(data[off:off + size])))
        last = 80
        for t in self.tables:
            require(t['offset'] >= last, 'overlapping/out-of-order tables')
            last = t['offset'] + t['size']
        require(self.tables[0]['offset'] == 80, 'unsupported tree start')
        self._table_cache = {}
        self.alias_groups, self.range_issues, self.read_only = [], [], False
        self._read_only_overlaps = read_only_overlaps
        self.nodes, self.resources, self.unsupported_attributes = [], [], []
        self._parse()

    def table(self, index):
        if index not in self._table_cache:
            t = self.tables[index]
            self._table_cache[index] = self.data[t['offset']:t['offset'] + t['size']]
        return self._table_cache[index]

    def _parse(self):
        tree, strings = self.table(0), self.table(3)
        pos = 0
        while pos < len(tree):
            h = struct.unpack('<7I', region(tree, pos, 28, 'node header'))
            require(h[1] <= 4096 and len(self.nodes) < 1000000, 'node/attribute limit exceeded')
            attrs = []
            raw = region(tree, pos, 28 + 16 * h[1], 'node')
            for i in range(h[1]):
                key, ty, a, b = struct.unpack_from('<4I', raw, 28 + 16 * i)
                attr = dict(name=cstring(strings, key), name_offset=key, type=ty, raw=[a, b],
                            offset=self.tables[0]['offset'] + pos + 28 + 16 * i)
                if ty == 1:
                    attr['value'] = struct.unpack('<i', struct.pack('<I', a))[0]
                elif ty == 2:
                    attr['value_hex'] = struct.pack('<I', a).hex()
                elif ty == 3:
                    region(strings, a, b + 1, 'attribute string')
                    require(strings[a + b] == 0, 'string length/terminator mismatch')
                    attr['value'] = cstring(strings, a)
                    require(len(attr['value'].encode()) == b, 'string length mismatch')
                elif ty in (6, 7):
                    table = self.table(6 if ty == 6 else 7)
                    values = region(table, a * 4, b * 4, 'array attribute')
                    attr['value_hex'] = values.hex()
                elif ty == 8:
                    file_size = self.tables[8]['size']
                    require(a <= file_size and b <= file_size - a,
                            f'invalid file reference: node={pos:#x}, attribute={attr["name"]!r}, '
                            f'field={attr["offset"]:#x}, relative_offset={a:#x}, length={b}, file_table_size={file_size}')
                elif ty == 9:
                    ids = self.table(1)
                    back = struct.unpack('<I', region(ids, a, 4, 'ID string'))[0]
                    require(back == pos, 'ID string loopback mismatch')
                    attr.update(value=cstring(ids, a + 4), loopback=back)
                elif ty == 11:
                    ids = self.table(2)
                    back, value = struct.unpack('<II', region(ids, a, 8, 'ID integer'))
                    require(back == pos, 'ID integer loopback mismatch')
                    attr.update(value=value, loopback=back)
                else:
                    self.unsupported_attributes.append(dict(node=pos, attribute=attr))
                attrs.append(attr)
            node = dict(offset=pos, absolute_offset=80 + pos, tag=cstring(strings, h[0]),
                        tag_offset=h[0], parent=h[2], previous=h[3], next=h[4],
                        first_child=h[5], last_child=h[6], size=len(raw), attributes=attrs)
            names = [a['value'] for a in attrs if a['type'] == 9 and a['name'] == 'id']
            require(len(names) <= 1, 'duplicate node ID')
            node['name'] = names[0] if names else None
            self.nodes.append(node)
            pos += len(raw)
        require(pos == len(tree) and self.nodes, 'incomplete tree')
        self._validate_links()
        for node in self.nodes:
            attrs = node['attributes']
            byname = {a['name']: a for a in attrs}
            declared = byname.get('type', {}).get('value')
            for attr in attrs:
                if attr['type'] != 8:
                    continue
                off, size = attr['raw']
                absolute = self.tables[8]['offset'] + off
                payload = self.data[absolute:absolute + size]
                kind, image, error = identify(payload)
                origsize = byname.get('origsize', {}).get('value')
                compression = 'unknown'
                if payload.startswith((PNG, b'DDS ', b'RCSF', b'<')):
                    compression = 'stored'
                if origsize is not None and origsize != size:
                    compression = 'unknown (origsize differs)'
                if 'compress' in byname or 'compression' in byname:
                    compression = 'unknown (explicit compression attribute)'
                expected = {'png': 'texture/png', 'dds': 'texture/dds'}.get(kind)
                supported = (image is not None and compression == 'stored' and declared == expected
                             and not self.unsupported_attributes and absolute % 16 == 0)
                rid = f'r{len(self.resources):05d}'
                # Untrusted names are metadata only. Filenames are flat, bounded, indexed and unique.
                safe = re.sub(r'[^A-Za-z0-9_.-]', '_', node['name'] or node['tag'])[:100]
                file = f'resources/{rid}_{safe}_{attr["name_offset"]}.{kind if kind != "unknown" else "bin"}'
                self.resources.append(dict(id=rid, name=node['name'], tag=node['tag'],
                    attribute=attr['name'], attribute_offset=attr['offset'], node_offset=node['offset'],
                    offset=absolute, relative_offset=off, size=size, offset_mod_16=absolute % 16,
                    declared_type=declared, kind=kind, compression=compression, sha256=sha(payload),
                    image=image, replacement_supported=supported,
                    unsupported_reason=None if supported else error or 'unverified declaration, alignment, compression or attributes',
                    file=file))
        self._classify_ranges()

    def _classify_ranges(self):
        groups = {}
        for item in self.resources:
            groups.setdefault((item['offset'], item['size']), []).append(item)
        # Check distinct physical spans. Equal pointers are a separate relation,
        # never evidence that arbitrary intersections are safe.
        previous_end = self.tables[8]['offset']
        furthest = None
        for (offset, size), members in sorted(groups.items()):
            gap = max(0, offset - previous_end)
            for item in members: item['preceding_gap'] = gap
            if not size:
                previous_end = max(previous_end, offset)
                continue  # Empty ranges own no bytes and cannot conflict.
            if len(members) > 1:
                ids = [x['id'] for x in members]
                group = dict(offset=offset, size=size, resource_ids=ids, sha256=members[0]['sha256'], relation='identical-shared-range')
                self.alias_groups.append(group)
                for item in members:
                    item['shared_with'] = [ident for ident in ids if ident != item['id']]
                    item['alias_group'] = f'{offset:#x}:{size}'
            if furthest and offset < furthest['end']:
                first = furthest['members'][0]
                second = members[0]
                contained = offset + size <= furthest['end'] or offset == first['offset']
                issue = dict(relation='contained-range-unverified' if contained else 'partial-overlap',
                    first=dict(ids=[x['id'] for x in furthest['members']], offset=first['offset'], size=first['size']),
                    second=dict(ids=[x['id'] for x in members], offset=offset, size=size))
                # One blocking relation per intersecting extent suffices; this
                # is not an exhaustive quadratic pair inventory.
                if len(self.range_issues) < 1024: self.range_issues.append(issue)
                if not self._read_only_overlaps:
                    raise Invalid(f'unsupported {issue["relation"]}: {first["id"]} '
                                  f'[{first["offset"]:#x}, +{first["size"]}] intersects '
                                  f'{second["id"]} [{offset:#x}, +{size}]; read-only extraction is available')
                self.read_only = True
            if not furthest or offset + size > furthest['end']:
                furthest = dict(end=offset + size, members=members)
            previous_end = max(previous_end, offset + size)
        if self.read_only:
            for item in self.resources:
                item['replacement_supported'] = False
                item['unsupported_reason'] = 'Read-only: unverified contained/partial file ranges; rebuilding or reference edits are blocked.'

    def _validate_links(self):
        nodes = {n['offset']: n for n in self.nodes}
        require(self.nodes[0]['parent'] == NULL and self.nodes[0]['previous'] == NULL
                and self.nodes[0]['next'] == NULL, 'invalid root links')
        for n in self.nodes:
            for key in ('parent', 'previous', 'next', 'first_child', 'last_child'):
                require(n[key] == NULL or n[key] in nodes, f'dangling {key} link')
            require((n['first_child'] == NULL) == (n['last_child'] == NULL), 'incomplete child links')
        visited, todo = {0}, [self.nodes[0]]
        while todo:
            parent = todo.pop()
            current, previous = parent['first_child'], NULL
            while current != NULL:
                require(current not in visited, 'tree cycle/multiple parents')
                n = nodes[current]
                require(n['parent'] == parent['offset'] and n['previous'] == previous,
                        'inconsistent parent/sibling links')
                visited.add(current)
                todo.append(n)
                previous, current = current, n['next']
            require(previous == parent['last_child'], 'last child mismatch')
        require(len(visited) == len(nodes), 'unreachable tree nodes')

    def manifest(self):
        result = dict(schema='rcof-lossless-1', magic='RCOF', version=0x110, byte_order='little',
            size=len(self.data), sha256=sha(self.data), tables=self.tables, nodes=self.nodes,
            resources=self.resources, unsupported_attributes=self.unsupported_attributes,
            summary=dict(nodes=len(self.nodes), resources=len(self.resources),
                kinds=dict(collections.Counter(r['kind'] for r in self.resources)),
                replacement_supported=sum(r['replacement_supported'] for r in self.resources)),
            limitations=['Only RCOF 0x110 with validated nonoverlapping ranges is supported.',
                'Repack is lossless layout reconstruction, not a relocating semantic compiler.',
                'RCSF/XML/unknown payloads are extracted opaque and cannot be replaced.',
                'Only equal-length PNG and BC DDS replacement is supported.',
                'No console acceptance, signature or firmware compatibility claim.'])
        # Preserve the canonical shape of existing nonaliased 0.3.0 projects.
        if self.alias_groups:
            result['shared_ranges'] = self.alias_groups
            result['limitations'][0] = 'RCOF 0x110: exact shared extents supported; distinct intersections require read-only inspection.'
        if self.read_only:
            result.update(read_only=True, range_issues=self.range_issues)
        return result


def write_new(path, data):
    p = Path(path)
    require(not p.is_symlink(), 'output symlink rejected')
    # xb also prevents an existing path (including source) being overwritten.
    with p.open('xb') as f:
        f.write(data)


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + '\n').encode()


def extract(data, out, *, read_only_overlaps=False):
    container = Container(data, read_only_overlaps=read_only_overlaps)
    manifest = container.manifest()
    out = Path(out)
    require(not out.exists(), 'extraction directory must be new')
    out.mkdir(parents=True)
    (out / 'resources').mkdir()
    layout = bytearray(data)
    for r in container.resources:
        start, end = r['offset'], r['offset'] + r['size']
        write_new(out / r['file'], data[start:end])
        layout[start:end] = b'\0' * r['size']
    write_new(out / 'layout.bin', layout)
    manifest['layout_sha256'] = sha(layout)
    write_new(out / 'manifest.json', json_bytes(manifest))
    if container.read_only:
        return dict(**manifest['summary'], read_only=True, range_issues=container.range_issues)
    return manifest['summary']


def child_file(root, relative):
    root = Path(root).resolve()
    p = root / relative
    require(not Path(relative).is_absolute() and '..' not in Path(relative).parts,
            'unsafe manifest path')
    require(p.resolve().is_relative_to(root) and not p.is_symlink(), 'manifest path escapes extraction')
    return p


def repack(directory):
    root = Path(directory)
    manifest = json.loads(read_file(child_file(root, 'manifest.json')))
    require(manifest.get('schema') == 'rcof-lossless-1', 'unsupported extraction schema')
    require(not manifest.get('read_only'), 'Read-only overlapping layout cannot be repacked; raw extraction is preserved.')
    layout = read_file(child_file(root, 'layout.bin'))
    require(sha(layout) == manifest['layout_sha256'], 'layout hash mismatch')
    result = bytearray(layout)
    extents = {}
    for r in manifest['resources']:
        payload = read_file(child_file(root, r['file']))
        require(len(payload) == r['size'] and sha(payload) == r['sha256'],
                f'{r["id"]}: extracted resource changed; use replace command')
        region(result, r['offset'], r['size'], 'repack resource')
        key = (r['offset'], r['size'])
        if key in extents:
            require(extents[key] == payload, 'Shared extraction files disagree; use validated copy-on-write reimport.')
            continue
        require(not any(result[r['offset']:r['offset'] + r['size']]), 'repack extents overlap or layout changed')
        result[r['offset']:r['offset'] + r['size']] = payload
        extents[key] = payload
    result = bytes(result)
    require(len(result) == manifest['size'] and sha(result) == manifest['sha256'], 'repack source identity mismatch')
    expected = Container(result).manifest()
    require(all(manifest.get(k) == v for k, v in expected.items()), 'manifest metadata changed')
    return result


def replace(data, resource_id, replacement):
    c = Container(data)
    found = [r for r in c.resources if r['id'] == resource_id]
    require(len(found) == 1, 'resource ID not found')
    r = found[0]
    require(r['replacement_supported'], f'resource replacement unsupported: {r["unsupported_reason"]}')
    require(not r.get('shared_with'), 'Shared resource editing requires copy-on-write; use Studio replacement/reimport, not the legacy in-place command.')
    require(len(replacement) == r['size'], 'replacement must have exactly the original stored length; relocation unsupported')
    info = png_info(replacement) if r['kind'] == 'png' else dds_info(replacement)
    require(info == r['image'], 'replacement image dimensions/format/header differ')
    # Block/header validation alone does not prove a DDS stream can be decoded.
    # Require an independent decoder for replacement, including the original.
    try:
        from PIL import Image
    except ImportError as e:
        raise Invalid('replacement requires Pillow (tested with 11.3.0)') from e
    require(info['width'] * info['height'] * 8 <= MAX_DECODE, 'image decode exceeds replacement limit')
    for payload in (data[r['offset']:r['offset'] + r['size']], replacement):
        try:
            with Image.open(io.BytesIO(payload)) as image:
                require(image.format == r['kind'].upper(), 'decoder image type differs')
                require(image.size == (info['width'], info['height']), 'decoder dimensions differ')
                image.load()
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as e:
            raise Invalid(f'independent image decode failed: {e}') from e
    result = data[:r['offset']] + replacement + data[r['offset'] + r['size']:]
    after = Container(result)
    require(len(after.resources) == len(c.resources), 'resource count changed')
    require(result[:r['offset']] == data[:r['offset']] and
            result[r['offset'] + r['size']:] == data[r['offset'] + r['size']:], 'non-target bytes changed')
    return result, dict(resource_id=resource_id, name=r['name'], offset=r['offset'], size=r['size'],
                        input_sha256=sha(data), output_sha256=sha(result),
                        changed_bytes=sum(a != b for a, b in zip(data, result)),
                        non_target_bytes_identical=True, console_acceptance='UNTESTED')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    for command in ('inspect', 'extract', 'replace', 'verify'):
        p = subs.add_parser(command)
        p.add_argument('input', type=Path)
        if command in ('extract', 'replace'):
            p.add_argument('--out', required=True, type=Path)
        if command == 'inspect':
            p.add_argument('--report', type=Path)
        if command == 'replace':
            p.add_argument('--resource', required=True)
            p.add_argument('--with', dest='replacement', required=True, type=Path)
        if command == 'verify':
            p.add_argument('other', type=Path)
    p = subs.add_parser('repack')
    p.add_argument('directory', type=Path)
    p.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'repack':
            result = repack(args.directory)
            write_new(args.out, result)
            answer = dict(status='PASS', sha256=sha(result), size=len(result), mode='lossless-layout-reconstruction')
        else:
            data = read_file(args.input)
            if args.command == 'inspect':
                m = Container(data, read_only_overlaps=True).manifest()
                if args.report:
                    write_new(args.report, json_bytes(m))
                answer = dict(status='PASS', sha256=m['sha256'], **m['summary'],
                              read_only=m.get('read_only', False), shared_ranges=m.get('shared_ranges', []),
                              range_issues=m.get('range_issues', []),
                              unsupported=[r['id'] for r in m['resources'] if not r['replacement_supported']],
                              unsupported_attributes=m['unsupported_attributes'])
            elif args.command == 'extract':
                answer = dict(status='PASS', **extract(data, args.out, read_only_overlaps=True))
            elif args.command == 'replace':
                result, answer = replace(data, args.resource, read_file(args.replacement))
                write_new(args.out, result)
                answer['status'] = 'PASS'
            else:
                other = read_file(args.other)
                Container(data)
                Container(other)
                equal = data == other
                answer = dict(status='PASS' if equal else 'FAIL', bytes_identical=equal,
                              input_sha256=sha(data), output_sha256=sha(other),
                              input_size=len(data), output_size=len(other))
                print(json.dumps(answer))
                return 0 if equal else 1
        print(json.dumps(answer))
        return 0
    except (Invalid, OSError, KeyError, TypeError, struct.error, json.JSONDecodeError) as e:
        print(json.dumps(dict(status='FAIL', error=str(e))), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
