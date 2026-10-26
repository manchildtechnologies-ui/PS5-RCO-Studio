# Validation report â€” 0.4.0

Date: 2026-10-26. **PASS for tested PC-side workflows; console acceptance UNTESTED.** No console was contacted.

| Check | Result |
| --- | --- |
| Original project automated suite | PASS â€” 182 tests, no failures/errors/skips |
| Curated repository automated suite | PASS — 182 tests, no failures/errors/skips |
| Initial private sample enumerate/extract | PASS â€” 8,164 logical resources |
| UI3 private sample enumerate/extract | PASS â€” 1,715 references, 1,707 physical ranges, eight shared groups |
| No-change reconstruction, both samples | PASS â€” byte-identical original/output SHA-256 |
| Compatible larger and smaller PNG | PASS â€” reopen and every-resource content/reference validation |
| Fixed-size DXT5/BC7 DDS | PASS |
| Shared PNG/DXT5/BC7 independent copy-on-write, multiple edits | PASS â€” synthetic raster alias fixtures |
| Real UI3 edit | PASS â€” a real PNG changed while shared SVG/zstd-declared locale bytes remained intact |
| Unknown partial/contained overlap | PASS â€” bounded read-only extraction; unsafe writes rejected |
| Original portable ZIP frozen GUI checks | PASS â€” both acceptance modes |
| Packaging-only candidate frozen GUI checks | PASS â€” both acceptance modes, Python absent from PATH |
| Candidate ordinary launch | PASS â€” visible title PS5 RCO Studio 0.4.0, clean exit 0 |
| Application/source behavior changes | NONE â€” all 22 Python modules and the executable byte-identical |
| Private input file identity | Unchanged after all runs |

Detailed sanitized evidence: [validation/validation-0.4.0.json](validation/validation-0.4.0.json). Raw local reports and sample data are private and excluded.

## No-change SHA-256

- Initial: `c0c5a01747c2b671574c604915e4dbd5f9d7cd7d2cba2677f739f3907f773e17`
- UI3: `ed0e9ef531a816b0b5e01a9fee23022a82b406d878b19205ed95515546354f24`

Each value matches both the input and rebuilt output. Original and candidate executable SHA-256: `83acf699a5f4002d2f680cad526a7289939f0402a3412e44fd8e17a22b67d99c`.

## Coverage limits

Two private sample byte sequences and synthetic fixtures establish this result. Real UI3 sharing is seven SVG groups and one zstd-declared locale group; shared raster behavior is covered synthetically. Neither proprietary compression semantics nor console acceptance is claimed. No clean-machine Windows-version matrix, hosted CI run or full visual-layout review is claimed. The candidate targets Windows 10/11 x64, omits 43 OS-supplied DLLs with unresolved redistribution provenance and keeps the tested executable unchanged. See THIRD-PARTY-AUDIT.md.

Asset checksums are supplied separately to avoid a circular archive hash. MIT licensing and public publication of this packaging candidate were explicitly approved by the maintainer.
