# PS5 RCO Studio 0.4.0

The first community release of the standalone Windows GUI for inspecting, extracting and editing verified PS5 RCOF resources. This release publishes the existing tested implementation with curated source, dependency notices and documentation.

## Supported workflows

- Browse resource identifiers, offsets, lengths, formats and metadata; preview supported PNG/DDS textures.
- Export individual resources or complete editable projects, stage compatible edits and rebuild to a separate output.
- Relocate larger or smaller PNGs with unchanged image geometry/encoding when the resource schema permits it.
- Replace DXT5 or DX10/BC7 DDS at the original stored size and exact header/mip layout.
- Preserve identical shared ranges during no-change rebuilding; use independent aligned copy-on-write for supported shared image edits.
- Reopen every rebuilt file and verify all changed and untouched resource payloads and references.

## Validation

All 182 automated tests pass. Two private sample checks pass: 8,164 initial resources and all 1,715 UI3 logical references enumerate/extract; no-change rebuilds are byte-identical. GUI and frozen acceptance cover larger/smaller PNGs, fixed-size DDS, multiple shared raster edits and unsafe-overlap rejection. UI3's real shared groups are SVG and zstd-declared locale data; shared PNG/DDS coverage uses synthetic fixtures.

**Modified RCO acceptance on an actual PS5 has not been verified.** PC-side validation does not establish console compatibility. No console was contacted.

## Install

Requires Windows 10/11 x64. Verify SHA256SUMS.txt, extract the entire Windows portable ZIP, then run PS5-RCO-Studio.exe. Keep the _internal folder beside it. Python and administrator rights are not required. The app is unsigned. A clean-machine Windows-version matrix has not been tested.

The community package retains the validated executable unchanged and omits 43 cached Windows system DLLs whose redistribution provenance could not be established; it uses the Windows-supplied components instead. Additional dependency notices accompany the package. The original working ZIP remains preserved locally.

## Known limitations

Recognized RCOF 0x110 layouts and verified schemas only. Variable-size DDS, changed geometry/encoding, general nested relocation, SVG/XML editing and proprietary/container decompression remain unsupported. RCSF text edits are restricted to equal UTF-16 byte length on verified unshared parents. Unknown partial/contained overlap permits bounded raw extraction but blocks rebuilding/editing. Unsupported resources are reported and preserved, not silently converted.

No firmware, RCO samples, SDKs or copyrighted artwork are included. No console deployment feature exists. Project source is available under the MIT License, copyright (c) 2026 manchildtechnologies-ui; dependency terms remain applicable independently of the source license.

## Assets

- Windows x64 portable ZIP
- Curated source ZIP
- Sanitized validation JSON and Markdown
- SHA256SUMS.txt

See README.md, COMPATIBILITY.md and THIRD-PARTY-AUDIT.md in the source distribution for usage, coverage and redistribution conditions.
