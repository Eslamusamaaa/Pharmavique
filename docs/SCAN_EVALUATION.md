# Measuring the scans (box, prescription, shelf)

Date: 2026-11-22. Tool: `scripts/scan_eval.py`. The scans call a vision model through OpenRouter and then
match what it read against the registry. This page says what was measured, what it does not show, and
how to measure real photos (Q-32).

## What was measured (generated pictures, the real models)

The tool drew pictures from real registry names and ran the same use case the API runs, with the models
in `PHARMAVIQUE_VISION_MODELS`. The text is clean and printed, so **these numbers are an upper bound**.

| Scan | Pictures | Medicines | Name read | Same brand first | Exact product first | Invented lines | Seconds per picture |
|---|---|---|---|---|---|---|---|
| Box | 4 | 4 | 4 (100%) | 4 (100%) | 3 (75%) | 0 | 6 (median) |
| Prescription | 3 | 12 | 12 (100%) | 12 (100%) | 10 (83%) | 0 | 18 (median) |
| Shelf | 4 | 32 | 32 (100%) | 32 (100%) | 21 (66%) | 0 | 12 (median), 22 at most |

- On prescriptions the dose was **not read in any line** (0 of 12), as the rule requires.
- "Exact product first" is lower than "same brand first" because one brand often has several register
  numbers (strengths, pack sizes). The person confirms the exact product after the scan.
- Not covered by these numbers: glare, angles, blur, crowded shelves, boxes whose name is partly hidden,
  Arabic-only boxes, handwritten prescriptions, photos taken in a pharmacy. They are the real risk.

## Measure real photos

1. Collect photos (the owner or a pharmacist; no patient names or personal details in them).
2. Put them in one folder, for example `data/eval/shelves/`, with a `labels.csv`:

   ```
   file,register_numbers
   shelf1.jpg,0902221712;0211234420;1802256914
   rx1.jpg,0902221712;1802256914
   ```

   The register numbers are the medicines that are really visible or written (look them up in the app).
3. Run it:

   ```powershell
   uv run python scripts/scan_eval.py --kind shelf --folder data/eval/shelves
   uv run python scripts/scan_eval.py --kind prescription --folder data/eval/prescriptions
   ```

   It prints, per picture and in total: names read, the right product first and in the first three, the
   same brand first and in the first three, lines the model invented, seconds per picture and, for
   prescriptions, that no dose was read.
4. Keep the folder out of git (`data/` is ignored) and record the result here with the date, the number
   of photos and who labelled them.

To try the pictures the tool draws, add `--keep <folder>` to save them. `--synthetic N` draws N pictures.

## What to do with the result

- Names read below about 90% on real shelves: tell the owner; the shelf scan stays usable only as a
  helper (every box is confirmed anyway) and the limit of 40 boxes and the prompt are the first things to tune.
- Invented lines: they are the dangerous failure (a name nobody printed). Raise it before anything else.
- Exact product first low but same brand first high: improve the matching with the strength read from
  the box (the search currently ranks by name).
