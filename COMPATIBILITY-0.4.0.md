# PS5 RCO Studio 0.4.0 â€” shared-resource compatibility

PS5-only PC workflow for recognized RCOF 0x110 containers. No console contact or
deployment. All 0.3.0 supported workflows remain subject to the same image/schema
restrictions, with these new shared-range rules:

| Case | Read / extract | No-change rebuild | Edit |
| --- | --- | --- | --- |
| Identical nonempty `(offset, length)` references | Supported, explicit peer IDs | Byte-identical; sharing retained | Verified image schema uses copy-on-write |
| Shared PNG | Supported | Preserved | Equal/larger/smaller stored sizes, same geometry/encoding; independent aligned allocation |
| Shared DXT5 DDS | Supported | Preserved | Copy-on-write at original size, identical header |
| Shared DX10/BC7 DDS | Supported | Preserved | Copy-on-write at original size, identical header |
| Shared SVG/XML/opaque or compressed locale data | Exact raw extraction | Preserved | Blocked; no new semantic editor/codec |
| Conflicting shared format/compression interpretations | Inspect/extract | Preserved | Blocked |
| Equal bytes at different offsets | Ordinary independent resources | Preserved | Normal existing replacement rules; no inferred deduplication |
| Distinct partially overlapping spans | Read-only bounded extraction | Blocked | Blocked |
| Contained spans or same start/different lengths | Read-only, marked unverified containment | Blocked | Blocked; not guessed to be nested |
| Empty references | No bytes claimed | Preserved | Not inferred to share a payload |
| Out-of-bounds file/table references or overlapping tables | Rejected with location/range details | Blocked | Blocked |
| Genuine nested RCSF/CXML | Own validated address space | Existing exact preservation | Existing restricted equal-byte strings, on unshared verified parent only |

Copy-on-write requires independently addressable type-8 texture attributes, known
texture metadata, consistent peer interpretations and a file table ending at EOF.
It never edits pooled bytes in place, never coalesces unrelated equal payloads,
and retains original/orphan bytes. DDS stored size, header, dimensions and mips
must match. No variable-size DDS, geometry changes, general nested relocation,
XML/SVG editing or container compression is newly claimed.

## Real reproducer

`Sce.PlayStation.PUI_UI3.rco`, privately supplied for local validation, is 39,313,104
bytes, SHA-256 `ed0e9ef531a816b0b5e01a9fee23022a82b406d878b19205ed95515546354f24`.
Old 0.3.0 fails during Open / Session / Container parsing, after recovering 1,715
file references. Eight exact shared ranges involve 16 IDs; no distinct partial
overlaps were observed. Seven groups declare SVG textures; the eighth pairs
`default` and `en-US` locale data with explicit `compress=zstd` metadata. Its
decompression/semantic interpretation is not implemented.

| Offset | Length | Shared IDs |
| --- | ---: | --- |
| 0x001181d0 | 1,302 | r00391, r00392 |
| 0x00a7be00 | 1,772 | r00625, r01562 |
| 0x00b6ba70 | 2,372 | r00772, r01563 |
| 0x00b6c3c0 | 2,202 | r00773, r01564 |
| 0x00c38eb0 | 1,357 | r01168, r01565 |
| 0x00c991b0 | 1,089 | r01236, r01566 |
| 0x00cd0cb0 | 1,754 | r01355, r01567 |
| 0x011b8c00 | 415,529 | r01568, r01575 |

Each pair uses separate valid type-8 attribute fields with the same pointer and
length. Alternate names (YouTube spelling, challenge/challenges, default/en-US)
and coherent ranges are consistent with intentional resource pooling. This is
structural evidence/inference, not proof of the producer's intent or console
behavior. Shared SVG/zstd bytes are not decoded or modified to make that inference.

The initial PUI sample and this supplied UI3 file are two distinct tested byte
sequences; firmware versions and derivation history are not inferred. Synthetic
PNG/DDS alias and malformed-range fixtures provide targeted coverage. No universal
PS5 compatibility or real-console acceptance is established.
