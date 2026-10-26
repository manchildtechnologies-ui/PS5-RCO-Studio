# Contributing

Use Python 3.12.10 on Windows with Tcl/Tk. Install `requirements-build.txt` in a virtual environment and run `python -m unittest discover -s tests -v` before proposing changes. GUI integration tests require an interactive desktop. The CI workflow runs these synthetic tests on Windows; private real-sample acceptance is performed separately.

Keep changes small and explain the format evidence, supported schemas, failure modes and validation results. Add synthetic malformed-range, preservation and round-trip tests for format changes. Never bypass a guard merely to accept an unfamiliar file. Reopen rebuilt files and verify every changed and untouched resource.

Do not submit Sony firmware, RCO/RCSF samples, extracted images or strings, proprietary SDK components, credentials or machine-specific paths. Report an issue with version, operation, sanitized error and synthetic reproducer where possible. Do not attach private `manifest.json`, `project.json`, `baseline.rco` or full acceptance logs: these can contain proprietary resource data and local paths.

Do not deploy experimental outputs to a console as part of this project's test process. PC-side correctness does not establish console acceptance. See COMPATIBILITY.md and THIRD-PARTY-AUDIT.md. Project source is under the MIT License; contributions should be compatible with that license.
