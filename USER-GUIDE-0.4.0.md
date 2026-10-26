# PS5 RCO Studio 0.4.0 â€” portable Windows x64

Extract the entire ZIP and run `PS5-RCO-Studio.exe`. Keep `_internal` beside it.
No installed Python, administrator rights, installer or registry association is
required. The app is unsigned; a clean-machine Windows-version matrix was not tested.

## Edit an extracted project

1. **Open RCO** selects a recognized local RCOF 0x110 file. The original is read-only.
2. **Extract All** writes a fresh editable project under a separate output folder:
   `resources/`, `manifest.json`, `layout.bin`, `project.json`, `baseline.rco`.
   The baseline is an exact recovery copy. Unknown resources are included.
3. Edit files inside `resources/` externally. Keep their filenames. Do not edit
   the manifest, preservation layout, baseline or project metadata.
4. **Scan edited folder** lists modified/unchanged, missing/additional files and
   unsupported modifications. READY means completeness checks passed; reimport
   still validates image and nested-structure compatibility.
5. **Reimport edited folder** validates the whole edit set before staging anything.
   Missing/additional files block import: restore or move them outside the project.
   Unsupported edits block the transaction with an explanation.
6. **Rebuild & validate / Repack** writes a new build directory and `validation.json`.
   **Save As** writes the exact new filename selected and its `.validation.json`.
   Existing output files are rejected; originals are never overwritten.
7. Reopen the output, preview replacements, and extract again if desired.

**Open extracted folder** opens its preserved baseline even if the original file
has moved. Reimport edits before repacking. **Show folder** opens it in Explorer.
A project export includes staged resources while retaining the original baseline.
Keep the whole folder for rollback. It contains local resource data and must not
be included in public source/release archives.

## Direct and batch replacement

Select a texture and **Stage replacement**. PNG stored size can grow/shrink when
its relocation schema is verified; dimensions, depth, color type and interlace
must match. DDS must retain its stored length, dimensions, encoding, mip layout
and exact header. PNG CRC/IDAT, DDS block lengths and independent decoding are checked.

Changed-size PNGs append at 16-byte alignment, updating their offset/length and
file-table size. Original bytes remain preserved: a smaller PNG can still grow
the container. Repeated staging composes from the baseline rather than accumulating
intermediate appends during one session.

**Replace multiple** maps exact extracted filenames to IDs and validates atomically.
Unmatched names are rejected rather than guessed. **Discard staged changes**
restores the in-memory baseline. Closing loses unsaved staged edits.

## Browse and inspect

Search identifiers/names/variants and filter formats or modification status.
Headings sort the flat list. **Hierarchy** shows recovered nodes/references in stored
order; metadata includes raw fields and the recovered resource path.

Staged image previews show **Original** and **Staged replacement** side by side.
**Thumbnails** displays pages of 48; click an image to select its resource. DDS
preview displays the first mip; the complete compatible encoded mip payload is preserved.

**Nested** decodes verified RCSF IDs/UTF-16 text or shows XML atlas inspection.
Select a string, edit text and **Stage string edit**. UTF-16 byte length must match;
shared/overlapping storage effects, embedded NUL and metadata changes are rejected.
A surrogate pair occupies two UTF-16 code units. **Extract nested** writes exact
raw data plus inspection JSON, strings JSON or XML. These are inspection aids;
edit raw project resources or use the string editor. XML editing/nested relocation
are not enabled.

**Validate** checks the current layout and all expected payloads without saving.
Every rebuild reopens written bytes, verifies every changed/untouched resource,
references, alignment and preservation bytes, and rechecks source identity.
**Logs / errors** records operations and error details; save its log to a new file.
Work runs in a background worker, with scan counts and an activity indicator.

## Restrictions and evidence

See `COMPATIBILITY-0.4.0.md`. Variable-size DDS, changed image geometry, XML editing,
arbitrary CXML compilation, character-table relocation and proprietary/container
compression are unsupported. Opaque data is preserved; incompatible edits fail.

No console/network/deployment features exist. PASS means PC structural/functional
validation. Real PS5 acceptance is untested. Two private samples and synthetic
fixtures establish coverage. Project hashes check consistency relative to the
baseline, not origin authenticity if an attacker replaces the entire project.

## Source and build

`python ps5_rco_studio.py [file.rco]` launches from source.
`python -m unittest discover -s tests -v` runs all regressions.
`python build_portable.py --sample file.rco` builds a new directory, runs frozen
acceptance, and ZIPs only on PASS. `python verify_portable.py` tests the extracted
ZIP with Python absent from PATH, in a fresh versioned release directory.

Tested: Python 3.12.10, Pillow 11.3.0, PyInstaller 6.22.3, Tcl 8.6.15. Requirements
files pin dependencies. Notices and `THIRD-PARTY-AUDIT.md` accompany the release.

## Shared resource data (0.4.0)

Exact identical offset/length pairs are explicit shared references, not duplicate
files to overwrite in place. Metadata lists every peer ID. Extraction writes one
resource file per logical reference; no-change rebuilds retain original sharing.
Changing a verified shared PNG/DXT5/BC7 resource uses independent copy-on-write,
even at the same length: its new data is appended at 16-byte alignment and only
its own file pointer is changed. Untouched peers continue to use the original
bytes. Multiple edited peers receive separate allocations. Variable-size DDS
remains unsupported. Conflicting interpretations or unknown reference metadata
block editing, while exact raw extraction remains available.

Distinct partial or contained ranges are not assumed to be aliases or nested
containers. Such files open read-only when table/range bounds are valid, with
detailed diagnostics. Repack, Save As, replacement and reimport are blocked.
Extract All and individual extraction preserve their exact bounded slices. Invalid
or out-of-bounds file/table references are still rejected. A genuine nested RCSF
uses its own address space and is distinct from an unverified contained interval.

Shared SVG and zstd-declared locale data in the UI3 test file are preserved
opaque; this release does not add SVG editing or a proprietary/container codec.
