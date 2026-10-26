"""Write a new offline experimental report and a clearly labeled local artifact."""
import argparse
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from Rcomage import rcof as r
from research.experiments import inspect_rcsf, inspect_xml, relocate_png_append_only
from studio.smoke import changed_png


def grow_png(payload):
    body = b'Comment\0Experimental append-only relocation probe'
    chunk = struct.pack('>I', len(body)) + b'tEXt' + body
    chunk += struct.pack('>I', zlib.crc32(b'tEXt' + body) & r.NULL)
    return payload[:-12] + chunk + payload[-12:]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('sample', type=Path)
    p.add_argument('--out', required=True, type=Path)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    original = r.read_file(args.sample)
    container = r.Container(original)
    report = dict(scope='EXPERIMENTAL — PC structural evidence only', source_sha256=r.sha(original),
                  nested=[], relocation=None, console_contacted=False, console_acceptance='UNTESTED')
    for item in container.resources:
        payload = original[item['offset']:item['offset'] + item['size']]
        if item['kind'] not in ('rcsf', 'xml'): continue
        try:
            result = inspect_rcsf(payload) if item['kind'] == 'rcsf' else inspect_xml(payload)
        except Exception as exc:
            result = dict(status='FAIL', error=str(exc))
        result.update(resource_id=item['id'], resource_name=item['name'], kind=item['kind'])
        report['nested'].append(result)
    target = next(x for x in container.resources if x['kind'] == 'png' and x['replacement_supported'])
    current = original[target['offset']:target['offset'] + target['size']]
    replacement = grow_png(changed_png(current))
    modified, report['relocation'] = relocate_png_append_only(original, target['id'], replacement)
    r.write_new(args.out / 'EXPERIMENTAL-relocated-NOT-CONSOLE-VALIDATED.rco', modified)
    r.write_new(args.out / 'larger-replacement.png', replacement)
    # Exercise the existing lossless extractor/repacker on the experimental file.
    r.extract(modified, args.out / 'relocated-extracted')
    reconstructed = r.repack(args.out / 'relocated-extracted')
    r.require(reconstructed == modified, 'Relocated artifact does not round-trip')
    report['relocation']['existing_extractor_repacker_roundtrip'] = True
    report['nested_summary'] = dict(rcsf=sum(x['kind'] == 'rcsf' for x in report['nested']),
        xml=sum(x['kind'] == 'xml' for x in report['nested']),
        decoded_strings=sum(len(x.get('strings', [])) for x in report['nested']),
        all_inspections_pass=all(x['status'] == 'PASS' for x in report['nested']))
    r.require(r.read_file(args.sample) == original, 'Original sample changed')
    report['original_unchanged'] = True
    report['status'] = 'EXPERIMENTAL_PC_PASS'
    r.write_new(args.out / 'research.json', r.json_bytes(report))
    print(json.dumps(dict(status=report['status'], nested=report['nested_summary'], relocation=report['relocation'])))


if __name__ == '__main__': main()
