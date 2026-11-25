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

## Measure real photos (the dataset format)

Decision of 2026-11-25: the photos come from the internet and from pictures people posted (a patient, a
group), for boxes, prescriptions and shelves. They can show people, so **the photos stay on this machine
and never go to git**; only the answer file and the results do.

1. Put the photos in `data/eval/images/` (the folder is ignored by git).
2. Write the answers in the committed file `eval/scan/labels.csv`:

   ```
   file,kind,register_numbers,source_url,notes
   box-001.jpg,box,0902221712,https://example.org/where-it-was-found,dim light
   rx-001.jpg,prescription,0902221712;1802256914,,printed
   shelf-001.jpg,shelf,0902221712;0211234420;1802256914,,
   ```

   - `file`: the photo's name inside `data/eval/images/`; `kind`: `box`, `prescription` or `shelf`.
   - `register_numbers`: the medicines really visible or written (look them up in the app), `;` apart.
   - `source_url`: where the photo came from (empty when the owner took it); `notes`: light, angle, hand
     writing.
   - **No patient, doctor or any other person's name, phone or id**, not in the file and not in the
     notes. The tool refuses a file with a column named like one (`patient`, `name`, `doctor`, `phone`,
     `id`).
3. Run it for one kind at a time and keep the result:

   ```powershell
   uv run python scripts/scan_eval.py --kind box --labels eval/scan/labels.csv --report eval/scan/result-box.json --labelled-by "the owner"
   ```

   It prints, per picture and in total: names read, the right product first and in the first three
   (recall at 1 and at 3), the same brand first and in the first three, lines the model invented,
   seconds per picture and, for prescriptions, that no dose was read. It then prints the **failure
   cases**: `name_not_read` (a medicine on the label that no line named), `wrong_product` (the name was
   read but the right product was not first; with the three it offered) and `extra_line` (a line that
   matches no labelled medicine, with whether it was called confident).
4. `--report` writes a JSON with the numbers, the cases and the confidence table, and nothing else (no
   image, no text that was read). Commit it and record the date, the number of photos and who
   labelled them below.

The older layout (`--folder` with a `labels.csv` next to the photos) still works.

### Not sure of the name: ask, do not guess

Each scanned line now says `confidence`: `confident` when the registry name that matches best scores at
least `PHARMAVIQUE_SCAN_MIN_SCORE` (default 0.9), otherwise `uncertain` (and always when no name matched).
A person confirms every line either way and no medical information appears before they do. For an
uncertain line the app says it is not sure, offers the three closest names, a "none of these" search by
name and a button to retake the photo.

**The 0.9 is a first value, not a measured one.** It comes from typed names (2026-11-25): a name printed
exactly scores 0.95 or more, one wrong letter about 0.7, an unrelated word 0.57 at most. Photos will
score differently. The last table the tool prints, for thresholds from 0.50 to 0.95, shows how many read
lines would count as confident and how many of those had the right product first, and how many right
ones would be asked about for nothing: choose the threshold from it once there are real photos.

## What to do with the result

- Names read below about 90% on real shelves: tell the owner; the shelf scan stays usable only as a
  helper (every box is confirmed anyway) and the limit of 40 boxes and the prompt are the first things to tune.
- Invented lines: they are the dangerous failure (a name nobody printed). Raise it before anything else.
- Exact product first low but same brand first high: improve the matching with the strength read from
  the box (the search currently ranks by name).
