# Price Alert Tool

Reads daily closing prices and a list of alert rules, finds every alert that fired, and prints a short summary per instrument and rule type: how many alerts, and the date of the latest one.

## Run it

```
python alerts.py prices.csv rules.json
python -m unittest -v
```

```
python alerts.py sample/prices.csv sample/rules.json

INFY level: 4 alert(s) | latest alert: 2026-09-26
INFY MA: 1 alert(s) | latest alert: 2026-10-19
TCS level: 6 alert(s) | latest alert: 2026-10-29
TCS MA: 2 alert(s) | latest alert: 2026-10-13
```

`sample/prices.csv` is deliberately dirty (text prices, blanks, a missing column, conflicting duplicates), so that run also prints 17 warnings to stderr. Alerts go to stdout, warnings to stderr, and bad files exit with code 2. 

## The two rules

- **Level** (`"type": "level"`): fires on the day the close crosses a price line. Yesterday at or past the line, today strictly past it. E.g. below 100: 105, 102, **98** fires on day 3.
- **MA cross** (`"type": "ma_cross"`, with `short` and `long`): the average of the last `short` closes overtakes the average of the last `long` closes (or falls under it). E.g. short 2, long 3, closes 10, 9, 8, 7, 9, 12: short is below long until day 6 (10.5 vs 9.33), so it fires on day 6.

## How it works

1. **Read** both files; columns are matched by header name, so order and case don't matter.
2. **Clean:** a bad row or bad rule is skipped with a warning instead of crashing, so one broken line doesn't hide every other alert.
3. **Group** rows per instrument (names compared ignoring case and spaces) and sort by real date.
4. **Detect:** compare yesterday with today for each rule.
5. **Print** the summary. Prices are `Decimal`, not float, so "equal" really means equal.

## Choices I made where the brief doesn't say

| Question | My choice | Why |
|---|---|---|
| Does touching the level count? | No; it fires the day it goes strictly past | "Crosses" means changing side. 105, 100, 98 still fires on day 3 |
| Does every re-crossing fire? | Yes | Each crossing is a new event |
| MA already above on its first measurable day? | No alert | Nothing crossed, and there is no "yesterday" |
| MA warm-up | First possible alert is row `long` + 1 | Needs both today's and yesterday's averages |
| Date gaps (weekends) | Yesterday = previous row | The file only has trading days |
| `infy` vs `INFY` | Same stock | Otherwise a rule silently finds no prices |
| Ambiguous date like `09/10/2026` | Skip and warn | A wrong guess puts a price on the wrong day without telling anyone |
| Conflicting duplicate prices | Later row wins, loud warning | I can't know which is true, so it must be visible |
| Duplicate rule ids | Keep both, warn | Dropping one would lose alerts |

My general rule: when the data is unclear, a loud warning is better than a quiet guess.

## Edge cases covered

- **Level:** starts past the level, stays past it, touch and bounce, touch then through, re-cross, single row.
- **MA:** too few rows, born above, equal then up, flat series, rules with short >= long.
- **Data:** unsorted rows, gaps, text/blank/zero/negative prices, impossible dates, missing columns, duplicates, `"1,520.50"`, BOM, Windows line endings, interleaved instruments.
- **Rules file:** missing or bad fields, unknown type, unknown instrument, duplicate ids, `r2` sorting before `r10`.

## Testing

90 tests, all passing: rule validation (20), messy data (19), MA rule (16), level rule (14), rule ordering (6), command line (6), duplicate prices (4), instrument case (3), duplicate rule ids (2). Two of them compare the code against a slow, simple version on random data, so those expected values don't come from my own judgement.

After I changed the command line to print summaries, I updated the command-line tests to match the new output, and I removed the test that compared the sample run to a saved expected file, because the sample rules had changed. I also made the sample prices messy on purpose, so the sample run exercises the warnings too.

## How I used the assistant

An AI assistant drafted the first version of the code and tests. I reviewed it, decided the behaviour in the table above, and changed the output format and the tests myself. Things the first draft got wrong and I had changed:

- Instrument names were case-sensitive, so a lowercase price file made a rule silently never fire.
- Two rules with the same id: the second was silently dropped.
- Rule ids were sorted as text (`r10` before `r2`).
- "Last duplicate wins" had only an ordinary warning, even though the result depends on file order.
- Values like `"1,520.50"` were rejected.

