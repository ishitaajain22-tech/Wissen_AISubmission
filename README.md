# Price Alert Tool

Reads daily closing prices and a list of alert rules, then prints which alerts fired and on which day.

**Run:** `python alerts.py prices.csv rules.json` (Python 3.8+, standard library only, nothing to install).
**Test:** `python -m unittest -v` (103 tests, about 1 second).
Alerts go to stdout, warnings to stderr, and the exit code is 2 on unreadable or invalid files. Nothing is hard-coded: prices and rules come only from the two files given on the command line (`sample/` and `cases/` are example data; a test runs one prices file against three different rules files and checks the output changes).

## How I used the assistant
The assistant drafted code and tests; I set the requirements and acted as reviewer. I made it dry-run the logic on small hand-checkable numbers until I could predict outputs myself, had it list every edge case with what the tool does in each, and decided which behaviours to change. I also questioned its claims rather than accepting them: how the sample output was produced, and whether rules could be hard-coded. Every design choice below is one I reviewed and can explain.

## What the assistant got wrong, and what I changed
| Assistant's first version | Problem | What I decided |
|---|---|---|
| Instrument names case-sensitive | `infy` vs `INFY` gives silently no alert | Case/space-insensitive; output prints the rule's spelling |
| Two rules with the same id: second silently dropped | Alerts lost | Keep both, loud warning, order by position in rules file |
| Rule ids sorted as plain text | `r10` before `r2` | Natural order (`r2` < `r10`), letters case-insensitive |
| Duplicate price rows: "last wins" with an ordinary warning | Result depends on file order | Conflicting values: loud `CONFLICTING` warning naming both lines; identical: ignored |
| Rejected plausible real values (`"1,520.50"`, `2026-09-01T15:30`, `"1500"`, `5.0`) | Good data skipped | Accepted; malformed forms (`"1,52"`) still rejected, not guessed |
| `sample/expected.txt` was the tool's own output | Not independent evidence | Treated only as a regression snapshot; correctness rests on hand-worked tests and a randomized comparison with a naive reference |

## What the tool does
Input 1, **prices.csv**: one row per instrument per day.
```
date,instrument,close
2026-09-01,INFY,1512.40
```
Input 2, **rules.json**: a list of rules. Each has a unique-ish `id`, an `instrument`, a `direction` (`above`/`below`) and a `type`:
```json
{"id":"r1","instrument":"INFY","type":"level","direction":"below","level":1500}
{"id":"r2","instrument":"TCS","type":"ma_cross","direction":"above","short":5,"long":20}
```
Output: one line per alert, `date rule_id instrument description`, sorted by date, then rule id.
```
2026-09-03 r1 INFY level below 1500
```

### How it works (five steps)
1. **Read** (`load_prices`, `load_rules`): both files are read from the command line. Columns are matched by header name, so order and case do not matter.
2. **Clean:** every row and rule is validated. A bad one is skipped with a warning; it never crashes the run, because one corrupt row should not hide every other alert.
3. **Group:** prices are grouped per instrument (name matched ignoring case and spaces) and sorted by real date.
4. **Detect** (`level_fires`, `ma_fires`): compare "yesterday" with "today" for each rule.
5. **Print** (`run`, `main`): sort by date, then rule id in natural order, then position in the rules file. Warnings go to stderr so stdout stays clean for piping.

### The two rules, precisely
**Level.** An alert fires on day *t* when yesterday's close was on the other side of the level *or exactly on it*, and today's close is strictly past it. For `below 100`: `prev >= 100 and today < 100`. Touching the line is not a crossing; the day it actually goes through is.

**Moving-average cross (short *S*, long *L*).** The short average is the mean of the last *S* closes and the long average the mean of the last *L* closes (simple averages over the instrument's rows). An `above` alert fires when the short average goes from `<=` the long average to `>` it; `below` is the mirror. Both today's and yesterday's averages must exist, so the earliest possible alert is row *L*+1.

**Implementation notes.**
- Prices are `Decimal`, not float, so "equal" really means equal (0.1+0.2 is not 0.3 in floats, which could fake or hide a crossing at an exact level).
- Window sums come from a running-total list, so each window costs one subtraction and a rule is linear in the number of rows.
- Averages are compared without dividing: `short_sum * L` versus `long_sum * S` has the same sign as `short_avg - long_avg`, and stays exact.

## Where the brief is silent (my calls, and why)
| Question | My choice | Why, and the alternative |
|---|---|---|
| Does touching the level count? | No. Fires on the day it goes strictly through | "Crosses" means changing sides. A strict reading (`prev > level`) would miss a real drop in 105, 100, 98 |
| Does every re-crossing fire? | Yes | Each crossing is a new event a user would want. Alternative: first crossing only, a one-line change |
| First measurable day already above (MA)? | No alert | It never crossed; it started there. Alternative: fire on first defined day |
| Equal averages, then short rises? | Fires | Equal is not "above", so the first day it is above is the crossing |
| Gaps in dates (weekends, holidays)? | "Yesterday" = previous row | The file holds trading days only; calendar days would invent rows |
| Different spellings (`infy`/`INFY`)? | Same instrument | One meaning only, so normalizing is safe; the alternative is a silent missed alert |
| Ambiguous date `09/10/2026`? | Skipped with warning | Could be 9 Oct or 10 Sep. A wrong guess misplaces a price silently; a skip is loud |
| Conflicting duplicate prices? | Later row wins, loud `CONFLICTING` warning | Cannot know which is true; the answer depends on file order, so it must be visible |
| Duplicate rule ids? | Keep both, warn | Dropping one would lose alerts |
| `r10` vs `r2` order? | Natural order | Plain text order looks wrong to a reader |

## Edge-case catalogue
**Level rule:** starts already past the level (silent); stays past (fires once); touch and bounce (silent); touch then through (fires on the through day); re-crossing (fires each time); single row (silent); level zero; `above` mirror cases.
**MA rule:** fewer rows than the window; exactly `long` rows; already above when first defined; equal then up; flat series; comes close but never crosses; up/down/up sequences; `short = 1`; window longer than the data; short >= long, zero or fractional windows (rule skipped).
**Prices file:** unsorted rows; weekend gaps; interleaved instruments; text, blank, zero, negative, NaN and infinite closes; impossible and wrongly formatted dates; missing columns and extra columns; any column order and header case; thousands separators (`"1,520.50"`, but malformed `"1,52"` rejected); scientific notation; timestamps in the date column; BOM; Windows line endings; header-only file; empty file; missing header; binary garbage.
**Duplicates:** identical rows (ignored with a note); conflicting rows (loud warning); duplicates across different spellings of a name.
**Rules file:** missing or empty id; bad or missing direction or type; non-numeric or `NaN` level; fractional, zero, negative or missing windows; short >= long; rule for an instrument with no prices; duplicate ids; numeric ids; extra fields ignored; empty list; not a list; invalid JSON.
**Output and CLI:** ordering by date, natural id order, file position; stdout/stderr separation; a warning count on stderr; exit code 2 with a clean message for missing, empty or invalid files.

## Hand-made realistic cases (`cases/`)
Each folder has `prices.csv`, `rules.json` and `expected.txt`. The expected output was worked out on paper before the tool was run, and each folder is also an automated test. Dates are real trading days (weekends skipped).

| Case | Rule | What it shows | Hand working | Expected |
|---|---|---|---|---|
| `01_infy_breakdown_touch_then_through` | INFY below 1500 | Re-crossing, weekend gap, touch then through | 1508.15→1496.80 crosses (09-03). Back to 1503.60, then 1499.90 crosses (09-08). Then exactly 1500.00 (not below), then 1497.30 goes through (09-10) | 09-03, 09-08, 09-10 |
| `02_hdfcbank_touch_and_bounce` | HDFCBANK below 1600 | Touch is not a cross | 1612 → 1600.00 → 1608.50: never strictly below | none |
| `03_tcs_trend_change_3_5` | TCS MA 3/5 above and below | Full MA cycle | Short minus long: -20, -13.3, **+1.3** (09-09, fires above), +24, +26, +4, **-32** (09-15, fires below) | 09-09 above, 09-15 below |
| `04_broker_export_mess` | INFY below 1500 | Unsorted rows, `infy`, quoted `"1,520.50"`, identical duplicate, blank price | Valid sorted: 1520.50, 1534.10, 1498.00 (crosses, 09-03), 1488.00 (already below) | 09-03 |
| `05_two_stocks_interleaved` | INFY below 1500, TCS above 3900 | Instruments never mix; two rules, same days | INFY 1510→1495 (09-02), 1505→1490 (09-04); TCS 3890→3905 (09-02), 3895→3910 (09-04) | 4 alerts, rule order within a day |
| `06_rule_id_natural_order` | ids `r10`, `r2`, `r1` | Natural sort | All three fire 09-02; printed `r1`, `r2`, `r10` | 3 lines, that order |
| `07_duplicate_rule_ids_both_kept` | two rules both `A` | Duplicate ids kept, file order | Both fire 09-02; TCS rule is first in the file | TCS line, then INFY line |
| `08_conflicting_duplicate_price` | INFY below 1500 | Conflict warning | 09-02 has 1490 and 1520; later (1520) is used, so no crossing | none, plus `CONFLICTING` |
| `09_sbin_flat_then_up_2_3` | SBIN MA 2/3 above | Equal then up | 09-03 and 09-04: short 810 = long 810; 09-07: 817.5 > 815 | 09-07 |
| `10_wipro_born_above_never_crosses` | WIPRO MA 3/5 above | Starts above, never crosses | First measurable day: short 406 > long 404, and it stays above | none |
| `11_invalid_rules_mixed_in` | 1 good + 3 bad rules | Bad rules skipped, good one still fires | `short 5 / long 5`, unknown stock, `sideways` all skipped with warnings | 1 alert |
| `12_bad_rows_shift_yesterday` | INFY below 1500 | Bad rows skipped; "yesterday" = previous valid row | `abc`, `0`, `-5`, `2026-02-30`, `09/10/2026` skipped; 1510 then 1490 | 09-07 |

`sample/messy50.csv` + `sample/messy_rules.json` is a 50-row stress file with 8 deliberately broken rows, a conflicting duplicate, a lowercase name and a mixed bag of rules. It is kept separate from the clean `sample/prices.csv` demo so that a change in error handling is not confused with a change in normal behaviour.

## Verification
- **103 automated tests** in these groups: level rule (14), moving-average rule (16), messy data (19), rule validation (20), command line (7), rule ordering (6), duplicate price rows (4), instrument case (3), duplicate rule ids (2), hand-made cases (12).
- **Independent references:** both rules are checked against slow, simple implementations on random data (exact fractions for the moving average), so those expected values are not my own judgement.
- **Hand-worked cases:** the 12 folders above were predicted on paper first; the tool matched all twelve.
- **Rules come from the file:** one prices file is run against three rules files with three different outputs, which catches hard-coding.
- One test the assistant wrote expected the wrong result on its first run; the tool was right, so the test was corrected.
- `sample/expected.txt` is a snapshot of the tool's own output and only guards against accidental change; it is not evidence of correctness.

## Known limits
- "Last duplicate wins" is arbitrary, hence the loud warning.
- Skipping a bad row changes what "yesterday" means, which can create or hide a crossing; it is warned about, not solved (case 12).
- Only ISO dates (`2026-09-01`, optionally with a time). A smarter version could infer day-first or month-first from the whole file.
- Simple moving averages only; no exponential averages.
- Coverage was not measured, so no percentage is claimed.