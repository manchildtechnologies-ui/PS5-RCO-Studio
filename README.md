# PS5 RCO Studio

A free, standalone Windows application for inspecting, extracting and editing verified image resources in PS5 RCOF containers. Version **0.4.0** adds safe handling of identical shared resource ranges and copy-on-write replacement.

**Modified RCO acceptance on an actual PS5 has not been verified.** PASS means PC-side validation against the tested files and synthetic fixtures. This project has no console deployment or network features and is not affiliated with Sony Interactive Entertainment.

## Install

Windows 10/11 x64. Download the portable ZIP from [Releases](https://github.com/manchildtechnologies-ui/PS5-RCO-Studio/releases/tag/v0.4.0), verify its SHA-256, extract the entire folder, then run `PS5-RCO-Studio.exe`. Keep `_internal` beside the executable. No installed Python or administrator privileges are needed. The executable is unsigned. A clean-machine Windows-version matrix has not been tested.

No firmware, RCO samples, SDK files or copyrighted artwork are supplied. Use resources you are authorized to access.

## Use

1. Open a local RCO. Browse identifiers, offsets, sizes, metadata, formats and shared reference peers.
2. Preview supported PNG/DDS images; export one resource or extract a complete project.
3. Stage a compatible replacement, or edit an extracted project's resource files and reimport them.
4. Rebuild to a **separate output directory**. Every output is reopened and all replacement and untouched resource payloads are verified. Existing output files are rejected.

PNG stored size may grow or shrink for verified schemas; image geometry and encoding must match. DXT5 and DX10/BC7 DDS retain their original stored size and exact header. Shared image edits append independent, 16-byte-aligned data and retain untouched peers' original bytes. Partial overlaps open read-only where bounds are valid; editing/rebuilding is blocked.

See [the user guide](USER-GUIDE-0.4.0.md), [compatibility](COMPATIBILITY.md), [command-line usage](docs/USAGE.md), [build instructions](docs/BUILD.md) and [validation report](VALIDATION-0.4.0.md).

## Source and tests

Use Python 3.12.10 with Tcl/Tk and the pinned dependencies:

```powershell
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
python ps5_rco_studio.py
```

All 182 existing tests pass, including GUI integration tests. Public tests use synthetic fixtures; the two privately supplied real RCO samples are deliberately excluded. See [contributing](CONTRIBUTING.md).

## Limitations

Support is specific to recognized RCOF 0x110 layouts, verified metadata and tested samples. Variable-size DDS, changed image geometry, SVG/XML editing, arbitrary compression, general nested relocation and unknown aliasing schemes are unsupported. RCSF strings have restricted equal-UTF-16-byte edits on verified unshared parents. Opaque data remains preserved and extractable; unsupported edits fail explicitly.

## Licensing

Project source is licensed under the [MIT License](LICENSE), copyright (c) 2026 manchildtechnologies-ui. The maintainer approved this grant and confirmed authority to license the original project source. Dependency notices and Windows runtime conditions retain their own terms; see [the redistribution audit](THIRD-PARTY-AUDIT.md). The project license does not grant rights in firmware, trademarks or resources opened by users.
