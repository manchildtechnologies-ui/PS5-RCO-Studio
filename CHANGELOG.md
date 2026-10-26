# Changelog

## 0.4.0

- Distinguishes exact shared resource ranges from partial overlap, unverified containment and invalid tables.
- Enumerates and extracts all 1,715 logical references in the tested UI3 sample; no-change reconstruction preserves its shared pointers byte for byte.
- Uses independent copy-on-write for verified shared PNG, DXT5 DDS and BC7 DDS replacements, including multiple edits.
- Keeps bounded unknown overlaps available for read-only extraction and blocks unsafe writes.
- Retains compatible larger/smaller PNG relocation, fixed-size DDS replacement, extracted-project workflows and automatic validation of every resource.
- Validation: 182 automated tests plus frozen GUI acceptance against two private samples. No console acceptance claim.

This first public release packages the existing 0.4.0 implementation. Release preparation changes documentation, notices and packaging only; it does not change parser, editor or rebuilder behavior. No additional historical release claims are inferred.
