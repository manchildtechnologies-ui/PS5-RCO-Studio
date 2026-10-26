# Build and verification

## Run from source

Windows x64, Python 3.12.10 with Tcl/Tk, Pillow 11.3.0 and PyInstaller 6.22.3 were tested. Use an isolated environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
python ps5_rco_studio.py
```

The public suite uses synthetic fixtures and does not need firmware. Tk tests require a desktop session. No private sample is downloaded by tests or CI.

## Build the frozen application

Provide your own authorized samples outside the repository. The existing helper creates a unique `builds` directory, builds a windowed PyInstaller application, runs frozen GUI acceptance and only creates archives after PASS:

```powershell
python build_portable.py --sample .\private\initial.rco --alias-sample .\private\ui3.rco
python verify_portable.py --out .\releases\local-verification
```

`--sample` is required; `--alias-sample` adds the real shared-range check. `verify_portable.py` reads locally generated `latest-release.json`, extracts the portable ZIP and runs it with Python removed from PATH. This is not a clean-machine test.

The helper and its archival source allowlist are preserved from the validated implementation. They do not implement public licensing approval and their generated source ZIP is not the curated community source distribution. Review and include the current community documents and approved project license separately before publishing a build.

## Community 0.4.0 packaging

The community package derives from the existing validated portable ZIP; its executable and retained runtime binaries are byte-identical. Forty-three cached `api-ms-win-*.dll`/`ucrtbase.dll` files are omitted because their redistribution provenance could not be verified. Windows 10/11 supplies these system components. Supplementary dependency notices and sanitized release documents are included. See THIRD-PARTY-AUDIT.md and VALIDATION-0.4.0.md.

Do not automatically publish a newly generated archive. Inspect dependency provenance and licenses, exclude all private resources and build logs, rerun tests and packaged GUI acceptance, and record hashes. The existing helper may collect OS DLLs again depending on the build environment; audit its output. Builds embed toolchain/runtime details and are not claimed bit-for-bit reproducible. The community package itself is separately verified.

## CI

`.github/workflows/tests.yml` runs the existing 182 synthetic tests on Windows. The first hosted CI run will happen only after approved publication; no hosted-CI PASS is claimed in the local report.
