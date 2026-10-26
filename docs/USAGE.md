# Usage

## GUI

See [USER-GUIDE-0.4.0.md](../USER-GUIDE-0.4.0.md) for direct replacement, batch import, extracted projects, nested inspection and validation. Original files remain untouched. Keep extracted projects private: they contain a complete baseline copy and resource data.

## Read-only inspection, extraction and no-change reconstruction

Run from the source directory with a local file you are authorized to inspect. All output names below must be new:

```powershell
python Rcomage/rcof.py inspect .\input.rco --report .\output\inspection.json
python Rcomage/rcof.py extract .\input.rco --out .\output\extracted
python Rcomage/rcof.py repack .\output\extracted --out .\output\no-change.rco
python Rcomage/rcof.py verify .\input.rco .\output\no-change.rco
```

Create `output` before writing the inspection report. `verify` compares entire files and expects equality; it is a no-change check, not an edited-image validator. Use the GUI's replacement workflow for relocation and shared-image copy-on-write. The low-level `replace` CLI is a legacy fixed-size interface and does not expose all GUI behavior.

For valid but partially overlapping ranges, inspect/extract works read-only; repack is deliberately blocked. Exact identical ranges preserve sharing on no-change rebuild. Read COMPATIBILITY.md before attempting edits.
