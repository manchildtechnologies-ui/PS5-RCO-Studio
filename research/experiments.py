"""Sample-focused structural research. Not a production replacement API."""
import io
import struct
import xml.etree.ElementTree as ET

from PIL import Image
from Rcomage import rcof as r


def inspect_rcsf(payload):
    r.require(payload[:4] == b'RCSF', 'Not an RCSF resource')
    # The observed layout matches the RCOF tables. Normalize just the magic in a
    # temporary in-memory view to reuse bounds/link/ID validation. No input write.
    view = r.Container(b'RCOF' + payload[4:])
    chars = view.table(4)
    values, unknown = [], []
    for node in view.nodes:
        for attribute in node['attributes']:
            if attribute['type'] == 4:
                index, length = attribute['raw']
                r.require(length % 2 == 0, 'Odd UTF-16 byte length')
                raw = r.region(chars, index * 2, length + 2, 'RCSF UTF-16')
                r.require(raw[-2:] == b'\0\0', 'RCSF string terminator missing')
                text = raw[:-2].decode('utf-16-le', errors='strict')
                values.append(dict(id=node['name'], attribute=attribute['name'],
                                   character_index=index, byte_length=length, text=text, sha256=r.sha(raw)))
            elif attribute['type'] not in (1, 2, 3, 6, 7, 8, 9, 11):
                unknown.append(dict(node=node['offset'], attribute=attribute))
    return dict(status='PASS' if not unknown else 'PARTIAL', sha256=r.sha(payload),
                magic='RCSF', version=0x110, nodes=len(view.nodes), strings=values,
                unknown_attributes=unknown, nested_file_resources=len(view.resources),
                interpretation='experimental: type-4 offset is a UTF-16 code-unit index; length is bytes',
                editing_supported=False)


def inspect_xml(payload):
    r.require(len(payload) <= 8 * 1024 * 1024, 'XML research size limit')
    r.require(b'<!DOCTYPE' not in payload.upper() and b'<!ENTITY' not in payload.upper(),
              'DTD/entities unsupported')
    root = ET.fromstring(payload)
    textures = root.findall('./textures/texture')
    info = root.find('info')
    valid_uv = True
    for node in textures:
        try:
            u0, u1, v0, v1 = (float(node.attrib[k]) for k in ('u0', 'u1', 'v0', 'v1'))
            valid_uv &= 0 <= u0 <= u1 <= 1 and 0 <= v0 <= v1 <= 1
        except (KeyError, ValueError):
            valid_uv = False
    return dict(status='PASS', sha256=r.sha(payload), root=root.tag, attributes=root.attrib,
                info=info.attrib if info is not None else None, elements=sum(1 for _ in root.iter()),
                atlas_entries=len(textures), uv_ranges_valid=valid_uv,
                editing_supported=False, serialization_losslessness='UNTESTED')


def relocate_png_append_only(data, identifier, replacement):
    """Experimental append-only PNG relocation, preserving every other span.

    Old payloads are retained as orphaned bytes. This is not compaction. Unknown
    references into file bytes, external references and console acceptance remain
    unverified. The GUI and production backend never call this function.
    """
    container = r.Container(data)
    matches = [x for x in container.resources if x['id'] == identifier]
    r.require(len(matches) == 1, 'Resource ID missing')
    target = matches[0]
    r.require(target['kind'] == 'png' and target['replacement_supported'], 'Only verified stored PNG is eligible')
    r.require(len(replacement) != target['size'], 'Experiment requires a different stored size')
    r.require(r.png_info(replacement) == target['image'], 'Image dimensions or encoding differ')
    info = target['image']
    r.require(info['width'] * info['height'] * 8 <= r.MAX_DECODE, 'Decode memory limit')
    with Image.open(io.BytesIO(replacement)) as image:
        image.load()
    files = container.tables[8]
    r.require(files['offset'] + files['size'] == len(data), 'File table does not end at EOF')
    padding = (-len(data)) % 16
    new_offset = len(data) + padding
    r.require(new_offset + len(replacement) <= r.MAX_FILE, 'Relocation exceeds size limit')
    result = bytearray(data + bytes(padding) + replacement)
    # Only these three u32 values in preexisting bytes are changed.
    struct.pack_into('<I', result, 76, len(result) - files['offset'])
    struct.pack_into('<II', result, target['attribute_offset'] + 8,
                     new_offset - files['offset'], len(replacement))
    parsed = r.Container(bytes(result))
    allowed = [(76, 80), (target['attribute_offset'] + 8, target['attribute_offset'] + 16)]
    cursor = 0
    for start, end in sorted(allowed):
        r.require(result[cursor:start] == data[cursor:start], 'Unexpected preexisting byte change')
        cursor = end
    r.require(result[cursor:len(data)] == data[cursor:], 'Unexpected trailing original byte change')
    for old, new in zip(container.resources, parsed.resources):
        if old['id'] != identifier:
            r.require(all(old[k] == new[k] for k in old if k != 'preceding_gap'),
                      'Unrelated resource changed')
    relocated = next(x for x in parsed.resources if x['id'] == identifier)
    r.require(relocated['offset'] == new_offset and relocated['sha256'] == r.sha(replacement), 'Relocated resource mismatch')
    # Undo only metadata changes and truncate the append; require byte identity.
    reversed_bytes = bytearray(result[:len(data)])
    for start, end in allowed: reversed_bytes[start:end] = data[start:end]
    r.require(bytes(reversed_bytes) == data, 'Experimental reversal differs')
    return bytes(result), dict(status='EXPERIMENTAL_PC_PASS', resource=identifier,
        original_sha256=r.sha(data), output_sha256=r.sha(result), original_size=len(data), output_size=len(result),
        old_offset=target['offset'], new_offset=new_offset, old_size=target['size'], new_size=len(replacement),
        alignment=16, padding=padding, orphaned_original_payload_retained=True,
        reverse_metadata_and_truncate_identical=True, console_acceptance='UNTESTED',
        limitations=['Unknown embedded/external references have not been ruled out.',
                     'Only append-only stored PNG relocation; no compaction or DDS format changes.',
                     'Not enabled in the GUI or production backend.'])
