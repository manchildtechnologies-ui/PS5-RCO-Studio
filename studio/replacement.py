"""Validated fixed-size patches and append-only PNG relocation for RCOF 0x110.

Promotes the tested research algorithm without enabling nested edits or DDS
relocation. Recompose from original bytes so repeated staging cannot leak appends.
"""
import io
import struct

from PIL import Image
from Rcomage import rcof as r
from .nested import validate_rcsf


def relocation_reason(container, item, *, copy_on_write=False):
    if container.read_only:
        return 'Read-only: contained/partial overlaps have unverified reference semantics.'
    if item['kind'] != 'png' and not (copy_on_write and item['kind'] == 'dds'):
        return 'Relocation supports PNG only. DDS must retain its original stored length and header.'
    if not item['replacement_supported']:
        return 'PNG relocation unavailable: ' + str(item['unsupported_reason'])
    files = container.tables[8]
    if files['offset'] + files['size'] != len(container.data):
        return 'PNG relocation unavailable: the file table does not end at EOF (trailing data cannot be relocated safely).'
    node = next(n for n in container.nodes if n['offset'] == item['node_offset'])
    allowed = {'id': 9, 'type': 3, 'src': 8, 'src_4k': 8, 'ninepatch': 6, 'margin': 6, 'alpha8': 3}
    if node['tag'] != 'texture' or len({a['name'] for a in node['attributes']}) != len(node['attributes']):
        return 'PNG relocation unavailable: unsupported texture node structure or duplicate attributes.'
    for attr in node['attributes']:
        if allowed.get(attr['name']) != attr['type']:
            return f'PNG relocation unavailable: unverified texture attribute {attr["name"]!r} (type {attr["type"]}); its references/size semantics are unknown.'
    if copy_on_write:
        peers = set(item.get('shared_with', []))
        for peer in container.resources:
            if peer['id'] in peers and any(peer[k] != item[k] for k in ('kind', 'declared_type', 'compression', 'image')):
                return 'Copy-on-write unavailable: shared references have conflicting format/compression interpretations.'
    return None


def needs_relocation(item, payload, pending):
    original_changed = r.sha(payload) != item['sha256']
    return item['id'] in pending and (len(payload) != item['size'] or
                                      (bool(item.get('shared_with')) and original_changed))


def validate_image(item, payload):
    r.require(item['replacement_supported'], 'Replacement unsupported: ' + str(item['unsupported_reason']))
    if item['kind'] == 'dds':
        r.require(len(payload) == item['size'],
                  'Variable-size DDS replacement is unsupported. Preserve the original stored length, DDS header, dimensions and encoding.')
    info = r.png_info(payload) if item['kind'] == 'png' else r.dds_info(payload)
    r.require(info == item['image'], 'Replacement image dimensions, color encoding or DDS header differ from the original.')
    r.require(info['width'] * info['height'] * 8 <= r.MAX_DECODE, 'Image decode exceeds replacement memory limit.')
    try:
        with Image.open(io.BytesIO(payload)) as decoded:
            r.require(decoded.format == item['kind'].upper(), 'Image decoder reports a different format.')
            decoded.load()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise r.Invalid('Independent replacement image decode failed: ' + str(exc)) from exc


def validate_payload(item, payload, original):
    if item['kind'] == 'rcsf':
        r.require(item['compression'] == 'stored', 'Compressed nested RCSF editing is unsupported.')
        return validate_rcsf(original, payload)
    return validate_image(item, payload)


def validate_rebuild(original, data, pending):
    """Reopen and compare every referenced payload, plus all preexisting bytes.

    Only fixed-size target spans, relocated type-8 offset/length words and the
    file-table size word may differ. All unaffected node references stay intact.
    """
    before, after = r.Container(original), r.Container(data)
    old_by_id = {x['id']: x for x in before.resources}
    r.require(set(pending) <= set(old_by_id), 'Staged resource ID does not exist.')
    r.require(len(before.resources) == len(after.resources), 'Resource count changed.')
    allowed, relocated, expected_append = [], [], len(original)
    identities = ('id', 'name', 'tag', 'attribute', 'attribute_offset', 'node_offset', 'declared_type',
                  'kind', 'compression', 'image', 'replacement_supported')
    verified = []
    for old, new in zip(before.resources, after.resources):
        r.require(all(old[k] == new[k] for k in identities), 'Resource metadata changed: ' + old['id'])
        payload = pending.get(old['id'], original[old['offset']:old['offset'] + old['size']])
        moved = needs_relocation(old, payload, pending)
        if moved:
            cow = bool(old.get('shared_with'))
            reason = relocation_reason(before, old, copy_on_write=cow)
            r.require(reason is None, reason)
            expected_append += (-expected_append) % 16
            r.require(new['offset'] == expected_append and new['offset'] % 16 == 0,
                      'Relocated PNG offset or alignment differs from the planned append.')
            expected_append += len(payload)
            allowed.append((old['attribute_offset'] + 8, old['attribute_offset'] + 16))
            relocated.append(dict(id=old['id'], old_offset=old['offset'], new_offset=new['offset'],
                                  old_size=old['size'], new_size=len(payload), alignment=16,
                                  copy_on_write=cow, original_shared_with=old.get('shared_with', [])))
        else:
            r.require(new['offset'] == old['offset'], 'Untouched or fixed-size resource moved: ' + old['id'])
            if old['id'] in pending and r.sha(payload) != old['sha256']:
                allowed.append((old['offset'], old['offset'] + old['size']))
        r.require(new['size'] == len(payload), 'Resource length differs from planned payload: ' + old['id'])
        actual = data[new['offset']:new['offset'] + new['size']]
        r.require(actual == payload, 'Replacement/untouched resource content mismatch: ' + old['id'])
        verified.append(dict(id=old['id'], size=new['size'], offset=new['offset'], sha256=r.sha(actual),
                             changed=old['id'] in pending))
    if relocated: allowed.append((76, 80))
    r.require(len(data) == expected_append, 'Unexpected appended/trailing bytes.')
    for index, (old, new) in enumerate(zip(before.tables, after.tables)):
        r.require(old['offset'] == new['offset'] and (index == 8 or old['size'] == new['size']),
                  'A table moved or changed size unexpectedly.')
    cursor = 0
    for start, end in sorted(allowed):
        r.require(start >= cursor and data[cursor:start] == original[cursor:start],
                  'Preexisting bytes outside approved replacement/reference spans changed.')
        cursor = end
    r.require(data[cursor:len(original)] == original[cursor:], 'Untouched original trailing bytes changed.')
    # Alignment padding is newly added data and must be deterministic zeroes.
    cursor = len(original)
    for item in relocated:
        r.require(not any(data[cursor:item['new_offset']]), 'Relocation padding is not zero-filled.')
        cursor = item['new_offset'] + item['new_size']
    return after, dict(relocations=relocated, verified_resources=verified,
                       shared_groups_before=before.alias_groups, shared_groups_after=after.alias_groups,
                       shared_references_preserved=True,
                       replacement_contents_verified=True, untouched_contents_verified=True,
                       non_target_bytes_identical=True, reference_updates_verified=True,
                       validation_scope='PC RCOF structure and all referenced payloads; console acceptance untested')


def compose(original, pending):
    container = r.Container(original)
    resources = {x['id']: x for x in container.resources}
    r.require(set(pending) <= set(resources), 'Unknown staged resource ID.')
    result = bytearray(original)
    relocations = False
    # Use tree order, independent of the order in which replacements were selected.
    for item in container.resources:
        if item['id'] not in pending: continue
        payload = pending[item['id']]
        original_payload = original[item['offset']:item['offset'] + item['size']]
        validate_payload(item, payload, original_payload)
        moved = needs_relocation(item, payload, pending)
        if not moved:
            # Retain the original backend's fixed-size validation contract.
            validate_payload(item, original_payload, original_payload)
            result[item['offset']:item['offset'] + item['size']] = payload
        else:
            reason = relocation_reason(container, item, copy_on_write=bool(item.get('shared_with')))
            r.require(reason is None, reason)
            padding = (-len(result)) % 16
            new_offset = len(result) + padding
            r.require(new_offset + len(payload) <= r.MAX_FILE, 'Relocated output exceeds the 512 MiB limit.')
            result += bytes(padding) + payload
            struct.pack_into('<II', result, item['attribute_offset'] + 8,
                             new_offset - container.tables[8]['offset'], len(payload))
            relocations = True
    if relocations:
        struct.pack_into('<I', result, 76, len(result) - container.tables[8]['offset'])
    output = bytes(result)
    parsed, validation = validate_rebuild(original, output, pending)
    return output, parsed, validation
