# Redistribution audit — 0.4.0 community release

## Scope and result

Reviewed all 22 Python source/test/build modules through an AST/import and sensitive-pattern inventory, packaging allowlists, runtime archive contents, retained notice files, build collection provenance and targeted filesystem/process operations. App dependencies are the Python standard library (including Tcl/Tk) and Pillow; PyInstaller is build tooling and supplies the frozen bootloader. The GUI opens Explorer through `os.startfile`; subprocess calls belong to build/verification helpers. No app console transport, credential use or network module was found. Scans are evidence, not a legal title certificate.

The curated repository contains independently developed PS5-only Python code and synthetic tests. It excludes the older PSP/PS3 C tool checkout, Rcomage/GimConv executables, SDKs, firmware, RCO/RCSF/DDS files, baselines, private manifests, extracted art/strings, local outputs, credentials and machine-specific paths. No Sony SDK or proprietary conversion binary is required or bundled. There are no existing shareable screenshots free of private resource content; screenshots are omitted.

The application ZIP's Python code filenames/constants and raw members were checked for the local account name; none were found. Source and public documents were scanned for credential patterns, private keys, personal account paths and absolute machine-specific paths. Raw private acceptance reports remain outside the repository. Synthetic fixtures construct their own bytes; real samples are not redistributed.

## Dependency inventory

| Component | Version/evidence | Redistribution basis and conditions |
| --- | --- | --- |
| CPython/stdlib | 3.12.10, installed distribution and DLL properties | PSF/history and included component notices; complete Python LICENSE retained |
| Pillow and bundled codecs | 11.3.0 wheel | Complete wheel LICENSE retained, including all bundled component notices; do not replace with a blanket MIT statement |
| Tcl/Tk | Tcl 8.6.15; bundled Tk 8.6 notice | Matching Tcl source-tag notice and installed Tk terms retained |
| PyInstaller bootloader | 6.22.3 | GPL with explicit bootloader exception permitting distribution under the application's chosen license; notice retained |
| OpenSSL | 3.0.16, DLL version and official CPython build properties | Apache-2.0; full matching LICENSE retained, including Apache text in Python's license |
| Expat | 2.7.1, DLL version | Matching upstream COPYING retained |
| zlib | 1.3.1, DLL version | Matching upstream LICENSE retained |
| libffi | 3.4.4, official CPython build properties | MIT-style notice included in full Python LICENSE |
| liblzma | XZ 5.2.5, official CPython build properties | liblzma public-domain designation in matching COPYING; GPL command-line tools are not bundled |
| Microsoft VCRUNTIME140/140_1 | 14.42.34438.0, byte-matches installed Python distribution | Microsoft additional conditions in Python LICENSE apply: unmodified redistribution only as part of an application on Windows, notices and applicable recipient terms retained; not open-source project code |

Version evidence for Python-linked binaries was compared with the installed official Python distribution. License URLs and downloaded notice hashes are in `third_party_notices/release-notice-provenance.json`; Tcl provenance is recorded separately. Every retained third-party notice remains intact.

## Original ZIP provenance gap and approved packaging

The original validated ZIP is preserved locally. Its 42 API-set DLLs plus `ucrtbase.dll` were collected from a cached libheif binary directory. They did not byte-match available local Windows SDK redist copies; their redistribution provenance is unresolved. **Do not publish that ZIP unchanged on the strength of this audit.**

The approved community package omits those 43 OS-supplied DLLs and targets Windows 10/11 x64. It retains the original executable and all other runtime binaries byte for byte, adds dependency notices and updates documentation. Both frozen GUI acceptance modes passed on this package. Windows-version coverage is one existing workstation, not a clean-machine matrix. No PS5 data is included in either public archive.

## Approved project license

The maintainer explicitly approved the MIT License, attributed to `manchildtechnologies-ui`, and confirmed authority to license the original project source. See LICENSE for the complete grant and disclaimer. Third-party licenses and Microsoft's Windows runtime conditions remain separate. MIT does not grant rights in firmware, trademarks or resources opened by users.

## Primary references

- [MIT license overview](https://choosealicense.com/licenses/mit/)
- [Python 3.12 license](https://docs.python.org/3.12/license.html)
- [CPython 3.12.10 dependency versions](https://raw.githubusercontent.com/python/cpython/v3.12.10/PCbuild/python.props)
- [PyInstaller exception](https://pyinstaller.org/en/stable/license.html)
- [Microsoft redistribution terms](https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution)
- [Microsoft UCRT deployment](https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment?view=msvc-170)

The maintainer approved public publication of the reviewed packaging candidate, with the 43 unresolved-provenance system DLLs excluded. This audit does not establish rights to every possible downstream use.
