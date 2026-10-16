
import csv
import json
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation

_warned = 0


def warn(msg, loud=False):
    global _warned
    _warned += 1
    print(("WARNING: " if loud else "warning: ") + msg, file=sys.stderr)


def _canon(name):
    return name.strip().casefold()


_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")


def parse_date(s):
    s = s.strip()
    if len(s) > 10 and s[10] in "T ": 
        s = s[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise ValueError(f"bad date {s!r}")


def parse_price(s):
    s = s.strip()
    if _THOUSANDS.match(s):  # "1,520.50"
        s = s.replace(",", "")
    try:
        v = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"bad close {s!r}")
    if not v.is_finite() or v <= 0:
        raise ValueError(f"close must be a positive number, got {s!r}")
    return v


def load_prices(path):
    series = {}
    with open(path, newline="", encoding="utf-8-sig") as f:  # utf-8-sig strips BOM
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("prices file is empty")
        reader.fieldnames = [(h or "").strip().lower() for h in reader.fieldnames]
        missing = {"date", "instrument", "close"} - set(reader.fieldnames)
        if missing:
            raise ValueError(f"prices file missing column(s): {sorted(missing)}")
        for row in reader:
            n = reader.line_num
            try:
                d = parse_date(row["date"] or "")
                inst = (row["instrument"] or "").strip()
                if not inst:
                    raise ValueError("empty instrument")
                close = parse_price(row["close"] or "")
            except ValueError as e:
                warn(f"prices line {n} skipped: {e}")
                continue
            days = series.setdefault(_canon(inst), {})
            if d in days:
                old, old_n = days[d]
                if old == close:
                    warn(f"prices line {n}: duplicate {inst} {d} identical to line {old_n}, ignored")
                else:
                    warn(f"CONFLICTING duplicate for {inst} {d}: line {old_n} says {old}, "
                         f"line {n} says {close}. Using line {n} (the later one) - "
                         f"check your data, results for {inst} may be wrong.", loud=True)
            days[d] = (close, n)
    return {i: [(d, c) for d, (c, _) in sorted(days.items())] for i, days in series.items()}


def _num(v):
    if isinstance(v, bool):
        raise ValueError("not a number")
    if isinstance(v, (int, Decimal)):
        d = Decimal(v)
    elif isinstance(v, str):
        try:
            d = Decimal(v.strip())
        except InvalidOperation:
            raise ValueError("not a number")
    else:
        raise ValueError("not a number")
    if not d.is_finite():
        raise ValueError("not a finite number")
    return d


def _whole(v):
    d = _num(v)
    if d != d.to_integral_value():
        raise ValueError("not a whole number")
    return int(d)


def _validate_rule(r):
    if not isinstance(r, dict):
        raise ValueError("rule is not an object")
    rid = r.get("id")
    if isinstance(rid, bool) or not isinstance(rid, (str, int)) or not str(rid).strip():
        raise ValueError("missing/invalid id")
    inst = r.get("instrument")
    if not isinstance(inst, str) or not inst.strip():
        raise ValueError("missing/invalid instrument")
    direction, typ = r.get("direction"), r.get("type")
    direction = direction.strip().lower() if isinstance(direction, str) else None
    typ = typ.strip().lower() if isinstance(typ, str) else None
    if direction not in ("above", "below"):
        raise ValueError("direction must be 'above' or 'below'")
    out = {"id": str(rid).strip(), "instrument": inst.strip(), "key": _canon(inst),
           "type": typ, "direction": direction}
    if typ == "level":
        try:
            out["level"] = _num(r.get("level"))
        except ValueError:
            raise ValueError("level must be a number")
    elif typ == "ma_cross":
        try:
            s, l = _whole(r.get("short")), _whole(r.get("long"))
        except ValueError:
            raise ValueError("short and long must be whole numbers")
        if s < 1 or l < 1:
            raise ValueError("short and long must be at least 1")
        if s >= l:
            raise ValueError("short must be smaller than long")
        out["short"], out["long"] = s, l
    else:
        raise ValueError(f"unknown rule type {r.get('type')!r}")
    return out


def load_rules(path):
    with open(path, encoding="utf-8-sig") as f:
        raw = json.load(f, parse_float=Decimal)
    if not isinstance(raw, list):
        raise ValueError("rules file must contain a JSON list")
    rules, first_seen = [], {}
    for i, r in enumerate(raw, start=1):
        try:
            rule = _validate_rule(r)
        except ValueError as e:
            warn(f"rule #{i} skipped: {e}")
            continue
        if rule["id"] in first_seen:
            warn(f"duplicate rule id {rule['id']!r} (rules #{first_seen[rule['id']]} and #{i}): "
                 f"keeping both; ties are ordered by position in the rules file", loud=True)
        else:
            first_seen[rule["id"]] = i
        rules.append(rule)
    return rules


def _fmt(d):
    return format(d.normalize(), "f")  # 1500.0 -> "1500", 12.50 -> "12.5"


def level_fires(rule, points):
    
    lvl, below = rule["level"], rule["direction"] == "below"
    for (_, prev), (d, cur) in zip(points, points[1:]):
        if (below and prev >= lvl and cur < lvl) or (not below and prev <= lvl and cur > lvl):
            yield d, f"level {rule['direction']} {_fmt(lvl)}"


def ma_fires(rule, points):
    S, L = rule["short"], rule["long"]
    if len(points) <= L:
        return
    pre = [Decimal(0)]
    for _, c in points:
        pre.append(pre[-1] + c)
    diffs = [(pre[i + 1] - pre[i + 1 - S]) * L - (pre[i + 1] - pre[i + 1 - L]) * S
             for i in range(L - 1, len(points))]  # diffs[k] <-> row L-1+k
    above = rule["direction"] == "above"
    for k in range(1, len(diffs)):
        p, c = diffs[k - 1], diffs[k]
        if (above and p <= 0 < c) or (not above and p >= 0 > c):
            yield points[L - 1 + k][0], f"ma_cross {S}/{L} {rule['direction']}"


def _natural_key(s):
    """r2 sorts before r10; letters compare case-insensitively."""
    parts = [p for p in re.split(r"([0-9]+)", s) if p != ""]
    return [(0, int(p), "") if (p.isascii() and p.isdigit()) else (1, 0, p.casefold())
            for p in parts]


def _run_with_rules(prices_path, rules_path):
    """Return all individual alert events plus the validated rules used to create them."""
    global _warned
    _warned = 0
    series = load_prices(prices_path)
    rules = load_rules(rules_path)
    out = []
    for idx, rule in enumerate(rules):
        points = series.get(rule["key"])
        if points is None:
            warn(f"rule {rule['id']}: no prices for {rule['instrument']}")
            continue
        fn = level_fires if rule["type"] == "level" else ma_fires
        for d, text in fn(rule, points):
            line = f"{d.isoformat()} {rule['id']} {rule['instrument']} {text}"
            # order: date, then rule id (natural), then id text, then file position
            out.append(((d, _natural_key(rule["id"]), rule["id"], idx), line))
    out.sort(key=lambda t: t[0])
    return [line for _, line in out], rules


def run(prices_path, rules_path):
    """Return every individual alert event; kept for tests and programmatic use."""
    lines, _ = _run_with_rules(prices_path, rules_path)
    return lines


def summarize_alerts(lines, rules):
    """Group individual events into one summary line per configured instrument/type."""
    groups = {}
    for rule in rules:
        key = (rule["key"], rule["type"])
        if key not in groups:
            label_type = "MA" if rule["type"] == "ma_cross" else "level"
            groups[key] = {"label": f"{rule['instrument']} {label_type}", "dates": []}

    for line in lines:
        parts = line.split(" ", 3)
        if len(parts) != 4:
            continue
        event_date, _rule_id, instrument, description = parts
        kind = "ma_cross" if description.startswith("ma_cross ") else "level"
        key = (_canon(instrument), kind)
        if key in groups:
            groups[key]["dates"].append(event_date)

    summary = []
    for group in groups.values():
        dates = group["dates"]
        count = len(dates)
        # Events are sorted chronologically, so the final date is the most recent.
        latest_date = max(dates) if dates else "none"
        summary.append(
            f"{group['label']}: {count} alert(s) | latest alert: {latest_date}"
        )
    return summary


def main(argv):
    if len(argv) != 3:
        print("usage: python alerts.py prices.csv rules.json", file=sys.stderr)
        return 2
    try:
        lines, rules = _run_with_rules(argv[1], argv[2])
    except (OSError, ValueError) as e:  # JSONDecodeError / UnicodeDecodeError are ValueErrors
        print(f"error: {e}", file=sys.stderr)
        return 2
    # Keep every event available through run(); the CLI presents a compact summary.
    for line in summarize_alerts(lines, rules):
        print(line)
    if _warned:
        print(f"note: {_warned} warning(s) above - some input was skipped or ambiguous",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
