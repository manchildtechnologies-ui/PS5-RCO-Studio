"""Read-only nested structures, using the validated research decoders."""
import json
import struct
from pathlib import Path
from Rcomage import rcof as r
from research.experiments import inspect_rcsf, inspect_xml


def inspect(payload, kind):
    if kind == 'rcsf':
        result = inspect_rcsf(payload)
        result['editing_supported'] = result['status'] == 'PASS' and not result['unknown_attributes']
        result['edit_restriction'] = 'Equal UTF-16 byte lengths only; no shared/overlapping storage changes.'
        return result
    if kind == 'xml': return inspect_xml(payload)
    raise r.Invalid('Nested decoding unsupported; exact raw resource remains exportable.')


def validate_rcsf(original, updated):
    r.require(len(original) == len(updated), 'RCSF editing currently requires identical stored length.')
    before, after = inspect_rcsf(original), inspect_rcsf(updated)
    r.require(before['status'] == after['status'] == 'PASS' and not before['unknown_attributes'],
              'Unverified nested attributes prevent RCSF editing.')
    r.require(len(before['strings']) == len(after['strings']), 'Nested string count changed.')
    chars_offset = struct.unpack_from('<I', original, 40)[0]
    spans, changed = [], []
    for old, new in zip(before['strings'], after['strings']):
        r.require(all(old[k] == new[k] for k in ('id', 'attribute', 'character_index', 'byte_length')),
                  'Nested string IDs or references changed.')
        if old['text'] != new['text']:
            r.require('\0' not in new['text'], 'Edited RCSF strings cannot contain embedded NUL.')
            start = chars_offset + old['character_index'] * 2
            spans.append((start, start + old['byte_length'])); changed.append(old['id'])
    cursor = 0
    for start, end in sorted(spans):
        r.require(start >= cursor and original[cursor:start] == updated[cursor:start],
                  'RCSF unknown metadata, overlapping strings or references changed.')
        cursor = end
    r.require(original[cursor:] == updated[cursor:], 'RCSF metadata outside text changed.')
    return dict(changed_strings=changed, offsets_and_unknown_metadata_preserved=True)


def replace_string(original, identifier, text):
    report = inspect_rcsf(original)
    matches = [x for x in report['strings'] if x['id'] == identifier]
    r.require(len(matches) == 1, 'Select one unique nested string ID.')
    old = matches[0]
    r.require('\0' not in text, 'Embedded NUL is unsupported in edited strings.')
    try: encoded = text.encode('utf-16-le', errors='strict')
    except UnicodeError as exc: raise r.Invalid('Invalid UTF-16 text: ' + str(exc)) from exc
    r.require(len(encoded) == old['byte_length'],
              'Nested edit requires the original UTF-16 byte length; character-table relocation is unsupported.')
    start = struct.unpack_from('<I', original, 40)[0] + old['character_index'] * 2
    updated = original[:start] + encoded + original[start + len(encoded):]
    checked = validate_rcsf(original, updated)
    r.require(set(checked['changed_strings']) <= {identifier}, 'This string shares/overlaps storage with another ID; edit rejected.')
    return updated


def export(payload, kind, directory):
    root = Path(directory); r.require(not root.exists(), 'Nested export directory must be new.')
    result = inspect(payload, kind)
    root.mkdir(parents=True)
    r.write_new(root / ('original.' + kind), payload)
    r.write_new(root / 'inspection.json', r.json_bytes(result))
    if kind == 'rcsf':
        # Names and text remain data in JSON, never output paths.
        r.write_new(root / 'strings.json', r.json_bytes(result['strings']))
    elif kind == 'xml':
        r.write_new(root / 'decoded.xml', payload)
    return dict(directory=str(root), status=result['status'], editing_supported=result.get('editing_supported', False))
