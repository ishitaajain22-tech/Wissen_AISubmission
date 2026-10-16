import contextlib
import datetime
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import alerts

HEADER = "date,instrument,close\n"


def _write(d, name, text, enc="utf-8"):
    p = os.path.join(d, name)
    with open(p, "w", encoding=enc, newline="") as f:
        f.write(text)
    return p


def run_err(prices, rules, header=HEADER, sep="\n", enc="utf-8"):
    """Run the tool; return (alert lines, stderr text)."""
    with tempfile.TemporaryDirectory() as d:
        p = _write(d, "p.csv", header + sep.join(prices) + sep, enc)
        r = _write(d, "r.json", rules if isinstance(rules, str) else json.dumps(rules))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            lines = alerts.run(p, r)
        return lines, err.getvalue()


def run(prices, rules, **kw):
    return run_err(prices, rules, **kw)[0]


def days(inst, closes, start=1):
    """One row per day in Sept 2026 (max 30 rows)."""
    return [f"2026-09-{start + i:02d},{inst},{c}" for i, c in enumerate(closes)]


def dated(inst, closes, base=datetime.date(2025, 1, 1)):
    return [f"{base + datetime.timedelta(days=i)},{inst},{c}" for i, c in enumerate(closes)]


def dates(lines):
    return [l[:10] for l in lines]


def lvl(direction, level, inst="X", id="r"):
    return {"id": id, "instrument": inst, "type": "level", "direction": direction, "level": level}


def ma(direction, s, l, inst="X", id="r"):
    return {"id": id, "instrument": inst, "type": "ma_cross", "short": s, "long": l,
            "direction": direction}


# Level rule
class LevelTests(unittest.TestCase):
    def test_brief_example(self):
        prices = ["2026-09-01,INFY,1520.50", "2026-09-01,TCS,3890.00", "2026-09-02,INFY,1534.10",
                  "2026-09-02,TCS,3902.25", "2026-09-03,INFY,1498.00"]
        self.assertEqual(run(prices, [lvl("below", 1500, "INFY", "r1")]),
                         ["2026-09-03 r1 INFY level below 1500"])

    def test_starts_past_level_no_fire(self):
        self.assertEqual(run(days("X", [90, 80, 70]), [lvl("below", 100)]), [])

    def test_staying_past_level_fires_once(self):
        self.assertEqual(dates(run(days("X", [110, 90, 80, 70]), [lvl("below", 100)])), ["2026-09-02"])

    def test_refires_on_each_new_crossing(self):
        out = run(days("X", [110, 90, 110, 90]), [lvl("below", 100)])
        self.assertEqual(dates(out), ["2026-09-02", "2026-09-04"])

    def test_touch_and_bounce_no_fire(self):
        self.assertEqual(run(days("X", [110, 100, 105]), [lvl("below", 100)]), [])

    def test_touch_then_through_fires_on_through_day(self):
        self.assertEqual(dates(run(days("X", [110, 100, 95]), [lvl("below", 100)])), ["2026-09-03"])

    def test_staying_exactly_at_level_no_fire(self):
        self.assertEqual(run(days("X", [110, 100, 100, 100]), [lvl("below", 100)]), [])

    def test_above_touch_then_through(self):
        self.assertEqual(dates(run(days("X", [90, 100, 101]), [lvl("above", 100)])), ["2026-09-03"])

    def test_above_touch_and_bounce(self):
        self.assertEqual(run(days("X", [90, 100, 99]), [lvl("above", 100)]), [])

    def test_single_row_no_fire(self):
        self.assertEqual(run(days("X", [90]), [lvl("below", 100)]), [])

    def test_level_formatting(self):
        self.assertTrue(run(days("X", [12, 10]), [lvl("below", 10.5)])[0].endswith("level below 10.5"))
        # float-looking and string levels print cleanly
        raw = '[{"id":"r","instrument":"X","type":"level","direction":"below","level":1500.0}]'
        self.assertTrue(run(days("X", [1600, 1400]), raw)[0].endswith("level below 1500"))

    def test_decimal_exactness(self):
        # 0.3 == 0.3 exactly (a touch), then a real drop
        self.assertEqual(dates(run(days("X", [0.3, 0.3, 0.2]), [lvl("below", 0.3)])), ["2026-09-03"])

    def test_zero_level_never_fires(self):
        self.assertEqual(run(days("X", [5, 4, 3]), [lvl("below", 0)]), [])

    def test_matches_naive_reference(self):
        rnd = random.Random(11)
        closes = [rnd.randint(95, 105) for _ in range(300)]
        rows = dated("X", closes)
        base = datetime.date(2025, 1, 1)
        for direction in ("below", "above"):
            exp = []
            for i in range(1, len(closes)):
                p, c = closes[i - 1], closes[i]
                if (direction == "below" and p >= 100 and c < 100) or \
                   (direction == "above" and p <= 100 and c > 100):
                    exp.append(str(base + datetime.timedelta(days=i)))
            self.assertEqual(dates(run(rows, [lvl(direction, 100)])), exp)
            self.assertTrue(exp)


#MA cross rule
class MaCrossTests(unittest.TestCase):
    def test_normal_cross_above(self):
        self.assertEqual(run(days("X", [10, 9, 8, 7, 9, 12]), [ma("above", 2, 3)]),
                         ["2026-09-06 r X ma_cross 2/3 above"])

    def test_normal_cross_below(self):
        self.assertEqual(run(days("X", [10, 12, 14, 13, 11, 9]), [ma("below", 2, 3)]),
                         ["2026-09-05 r X ma_cross 2/3 below"])

    def test_wrong_direction_silent(self):
        self.assertEqual(run(days("X", [10, 9, 8, 7, 9, 12]), [ma("below", 2, 3)]), [])

    def test_too_few_rows(self):
        self.assertEqual(run(days("X", [10, 9, 8]), [ma("above", 2, 3), ma("below", 2, 3, id="b")]), [])

    def test_four_rows_is_the_minimum_possible(self):
        self.assertEqual(dates(run(days("X", [10, 10, 5, 50]), [ma("above", 2, 3)])), ["2026-09-04"])

    def test_already_above_when_first_defined_no_fire(self):
        self.assertEqual(run(days("X", [1, 1, 9, 9]), [ma("above", 2, 3)]), [])

    def test_equal_then_up_fires(self):
        self.assertEqual(dates(run(days("X", [5, 5, 5, 5, 9]), [ma("above", 2, 3)])), ["2026-09-05"])

    def test_touches_equal_but_never_crosses(self):
        self.assertEqual(run(days("X", [10, 9, 8, 7, 8, 5]), [ma("above", 2, 3)]), [])

    def test_up_then_down_then_up_sequence(self):
        closes = [10, 9, 8, 7, 12, 4, 15]  # above at d5; below at d7
        self.assertEqual(dates(run(days("X", closes), [ma("above", 2, 3)])), ["2026-09-05"])
        self.assertEqual(dates(run(days("X", closes), [ma("below", 2, 3)])), ["2026-09-07"])

    def test_two_crossings_same_direction(self):
        closes = [10, 9, 8, 7, 12, 4, 3, 2, 30]  # above fires at d5 and d9
        self.assertEqual(len(run(days("X", closes), [ma("above", 2, 3)])), 2)

    def test_flat_series_never_fires(self):
        self.assertEqual(run(days("X", [5] * 30), [ma("above", 2, 3), ma("below", 2, 3, id="b")]), [])

    def test_short_of_one_compares_close_to_long_average(self):
        # d3 close10 vs L10 (equal); d4 close12 vs L10.67 -> above
        self.assertEqual(dates(run(days("X", [10, 10, 10, 12]), [ma("above", 1, 3)])), ["2026-09-04"])

    def test_window_longer_than_data(self):
        self.assertEqual(run(days("X", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]), [ma("above", 5, 20)]), [])

    def test_two_ma_rules_same_instrument(self):
        out = run(days("X", [10, 9, 8, 7, 9, 12]), [ma("above", 2, 3, id="a"), ma("above", 1, 3, id="b")])
        self.assertIn("a X ma_cross 2/3 above", out[0] if "2026-09-06 a" in out[0] else out[1])
        self.assertGreaterEqual(len(out), 1)

    def test_no_float_drift(self):
        prices = days("X", [0.1, 0.2, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3])
        self.assertEqual(run(prices, [ma("above", 2, 4), ma("below", 2, 4, id="b")]), [])

    def test_matches_naive_fraction_reference(self):
        rnd = random.Random(7)
        closes = [round(100 + rnd.uniform(-5, 5), 2) for _ in range(200)]
        S, L = 5, 20
        base = datetime.date(2025, 1, 1)
        avg = lambda i, n: sum(Fraction(str(c)) for c in closes[i - n + 1:i + 1]) / n
        for direction in ("above", "below"):
            exp = []
            for i in range(L, len(closes)):
                p, c = avg(i - 1, S) - avg(i - 1, L), avg(i, S) - avg(i, L)
                if (direction == "above" and p <= 0 < c) or (direction == "below" and p >= 0 > c):
                    exp.append(str(base + datetime.timedelta(days=i)))
            self.assertTrue(exp)
            self.assertEqual(dates(run(dated("X", closes), [ma(direction, S, L)])), exp)


# real-data messy
class RealDataTests(unittest.TestCase):
    def test_out_of_order_dates(self):
        prices = ["2026-09-03,X,90", "2026-09-01,X,110", "2026-09-02,X,105"]
        self.assertEqual(dates(run(prices, [lvl("below", 100)])), ["2026-09-03"])

    def test_dates_sort_as_dates_not_text(self):
        prices = ["2026-10-01,X,90", "2026-09-30,X,110", "2026-09-9,X,120"]  # last one is invalid
        self.assertEqual(dates(run(prices, [lvl("below", 100)])), ["2026-10-01"])

    def test_interleaved_instruments_dont_mix(self):
        prices = ["2026-09-01,A,110", "2026-09-01,B,90", "2026-09-02,A,90", "2026-09-02,B,110"]
        out = run(prices, [lvl("below", 100, "A", "r1"), lvl("below", 100, "B", "r2")])
        self.assertEqual(out, ["2026-09-02 r1 A level below 100"])

    def test_missing_days_use_previous_row(self):
        self.assertEqual(len(run(["2026-09-04,X,110", "2026-09-08,X,90"], [lvl("below", 100)])), 1)

    def test_one_instrument_missing_a_day_does_not_affect_another(self):
        prices = ["2026-09-01,A,110", "2026-09-02,A,90", "2026-09-01,B,110", "2026-09-03,B,90"]
        out = run(prices, [lvl("below", 100, "A", "a"), lvl("below", 100, "B", "b")])
        self.assertEqual(dates(out), ["2026-09-02", "2026-09-03"])

    def test_bad_rows_skipped_not_crash(self):
        prices = ["2026-09-01,X,110", "garbage,X,5", "2026-09-02,X,abc", "2026-09-02,X,",
                  "2026-09-02,X,nan", "2026-09-02,X,inf", "2026-09-02,X,-4", "2026-09-02,X,0",
                  "2026-02-30,X,50", "2026-09-02,,50", "2026-09-02,X,₹90", "2026-09-03,X,90"]
        out, err = run_err(prices, [lvl("below", 100)])
        self.assertEqual(dates(out), ["2026-09-03"])
        self.assertGreaterEqual(err.count("skipped"), 10)

    def test_short_and_long_rows(self):
        prices = ["2026-09-01,X,110", "2026-09-02,X", "2026-09-03,X,90,extra,cols", "", "2026-09-04,X,80"]
        self.assertEqual(dates(run(prices, [lvl("below", 100)])), ["2026-09-03"])

    def test_timestamps_in_date_column(self):
        prices = ["2026-09-01T00:00:00,X,110", "2026-09-02 15:30,X,90"]
        self.assertEqual(dates(run(prices, [lvl("below", 100)])), ["2026-09-02"])

    def test_thousands_separator_and_scientific_notation(self):
        prices = ['2026-09-01,X,"1,520.50"', '2026-09-02,X,"1,490.00"']
        self.assertEqual(len(run(prices, [lvl("below", 1500)])), 1)
        self.assertEqual(len(run(["2026-09-01,X,1.1e2", "2026-09-02,X,9E1"], [lvl("below", 100)])), 1)
        _, err = run_err(['2026-09-01,X,"1,52"'], [lvl("below", 100)])
        self.assertIn("skipped", err)

    def test_header_variants(self):
        prices = ["2026-09-01,X,110", "2026-09-02,X,90"]
        out = run(prices, [lvl("below", 100)], header="Date, Instrument ,CLOSE\n")
        self.assertEqual(len(out), 1)
        out = run(["110,X,2026-09-01", "90,X,2026-09-02"], [lvl("below", 100)], header="close,instrument,date\n")
        self.assertEqual(len(out), 1)
        out = run(["2026-09-01,110,x", "2026-09-02,90,x"], [lvl("below", 100, "X")], header="date,close,instrument\n")
        self.assertEqual(len(out), 1)

    def test_extra_columns_ignored(self):
        out = run(["2026-09-01,X,110,NSE,1000", "2026-09-02,X,90,NSE,900"], [lvl("below", 100)],
                  header="date,instrument,close,exchange,volume\n")
        self.assertEqual(len(out), 1)

    def test_bom_utf8(self):
        self.assertEqual(len(run(days("X", [110, 90]), [lvl("below", 100)], enc="utf-8-sig")), 1)

    def test_crlf_line_endings(self):
        out = run(days("X", [110, 90]), [lvl("below", 100)], header="date,instrument,close\r\n", sep="\r\n")
        self.assertEqual(len(out), 1)

    def test_header_only_and_no_rows(self):
        self.assertEqual(run([], [lvl("below", 100)]), [])

    def test_unknown_instrument_warns_and_others_still_work(self):
        out, err = run_err(days("X", [110, 90]), [lvl("below", 100, "NOPE", "a"), lvl("below", 100, "X", "b")])
        self.assertEqual(out, ["2026-09-02 b X level below 100"])
        self.assertIn("no prices for NOPE", err)

    def test_missing_required_column_is_an_error(self):
        with self.assertRaises(ValueError):
            run(["2026-09-01,110"], [], header="date,close\n")

    def test_no_header_row_is_an_error(self):
        with self.assertRaises(ValueError):
            run(["2026-09-02,X,90"], [], header="2026-09-01,X,110\n")

    def test_empty_prices_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            p, r = _write(d, "p.csv", ""), _write(d, "r.json", "[]")
            with self.assertRaises(ValueError):
                alerts.run(p, r)

    def test_large_input_runs(self):
        rnd = random.Random(1)
        rows, p = [], 100.0
        for inst in ("AAA", "BBB"):
            p = 100.0
            for i in range(20000):
                p = max(1.0, round(p + rnd.uniform(-1, 1), 2))
                rows.append(f"{datetime.date.fromordinal(700000 + i)},{inst},{p}")
        rnd.shuffle(rows)
        out = run(rows, [ma("above", 5, 20, "AAA", "a"), ma("below", 5, 20, "BBB", "b"), lvl("below", 100, "AAA", "c")])
        self.assertEqual(out, sorted(out, key=lambda l: l[:10]))
        self.assertGreater(len(out), 100)


class InstrumentCaseTests(unittest.TestCase):
    def test_price_and_rule_case_differ(self):
        out = run(days("infy", [110, 90]), [lvl("below", 100, "INFY", "r1")])
        self.assertEqual(out, ["2026-09-02 r1 INFY level below 100"])  # prints rule's spelling

    def test_mixed_case_rows_form_one_series(self):
        prices = ["2026-09-01,INFY,110", "2026-09-02,Infy,90"]
        self.assertEqual(len(run(prices, [lvl("below", 100, "infy")])), 1)

    def test_whitespace_in_prices_and_rules(self):
        self.assertEqual(len(run(["2026-09-01, X ,110", "2026-09-02,X ,90"], [lvl("below", 100, " x ")])), 1)


class DuplicateRuleIdTests(unittest.TestCase):
    def test_both_kept_ordered_by_file_position(self):
        prices = days("A", [110, 90]) + days("B", [110, 90])
        out, err = run_err(prices, [lvl("below", 100, "B", "r1"), lvl("below", 100, "A", "r1")])
        self.assertEqual(out, ["2026-09-02 r1 B level below 100", "2026-09-02 r1 A level below 100"])
        self.assertIn("duplicate rule id", err)

    def test_same_id_same_instrument_both_listed(self):
        out = run(days("X", [110, 90]), [lvl("below", 100, "X", "r1"), lvl("below", 105, "X", "r1")])
        self.assertEqual(len(out), 2)


class RuleOrderingTests(unittest.TestCase):
    def ids(self, rule_ids):
        prices = days("X", [110, 90])
        out = run(prices, [lvl("below", 100, "X", i) for i in rule_ids])
        return [l.split()[1] for l in out]

    def test_date_first_then_id(self):
        prices = days("A", [110, 90, 80, 120, 90]) + days("B", [110, 90])
        out = run(prices, [lvl("below", 100, "A", "a"), lvl("below", 100, "B", "z")])
        self.assertEqual([l[:10] + l.split()[1] for l in out], ["2026-09-02a", "2026-09-02z", "2026-09-05a"])

    def test_natural_number_order(self):
        self.assertEqual(self.ids(["r10", "r2", "r1", "r11", "r9"]), ["r1", "r2", "r9", "r10", "r11"])

    def test_letters_case_insensitive(self):
        self.assertEqual(self.ids(["B", "a"]), ["a", "B"])

    def test_prefix_ids_do_not_crash_and_are_stable(self):
        self.assertEqual(self.ids(["r1a", "r1", "r01"]), ["r01", "r1", "r1a"])

    def test_numeric_ids_in_json(self):
        prices = days("X", [110, 90])
        out = run(prices, [lvl("below", 100, "X", 10), lvl("below", 100, "X", 2)])
        self.assertEqual([l.split()[1] for l in out], ["2", "10"])

    def test_ids_with_unicode_digits_do_not_crash(self):
        self.assertEqual(len(self.ids(["r²", "r2"])), 2)


class DuplicatePriceRowTests(unittest.TestCase):
    def test_conflicting_duplicates_warn_loudly_last_wins(self):
        out, err = run_err(["2026-09-01,X,110", "2026-09-02,X,150", "2026-09-02,X,90"], [lvl("below", 100)])
        self.assertEqual(len(out), 1)
        self.assertIn("CONFLICTING", err)
        self.assertIn("150", err)
        self.assertIn("90", err)

    def test_result_depends_on_file_order_so_it_must_warn(self):
        out, err = run_err(["2026-09-01,X,110", "2026-09-02,X,90", "2026-09-02,X,150"], [lvl("below", 100)])
        self.assertEqual(out, [])
        self.assertIn("CONFLICTING", err)

    def test_identical_duplicates_are_harmless(self):
        out, err = run_err(["2026-09-01,X,110", "2026-09-02,X,90", "2026-09-02,X,90"], [lvl("below", 100)])
        self.assertEqual(len(out), 1)
        self.assertNotIn("CONFLICTING", err)
        self.assertIn("identical", err)

    def test_duplicates_across_spelling_of_instrument(self):
        _, err = run_err(["2026-09-01,INFY,110", "2026-09-01,infy,120"], [lvl("below", 100, "INFY")])
        self.assertIn("CONFLICTING", err)


# rule validation
class RuleValidationTests(unittest.TestCase):
    def good_with(self, bad_rules):
        out, err = run_err(days("X", [110, 90]), bad_rules + [lvl("below", 100, "X", "ok")])
        self.assertEqual(out, ["2026-09-02 ok X level below 100"])
        self.assertIn("skipped", err)

    def test_missing_id(self): self.good_with([{"instrument": "X", "type": "level", "direction": "below", "level": 1}])
    def test_empty_id(self): self.good_with([lvl("below", 1, id="")])
    def test_bool_id(self): self.good_with([lvl("below", 1, id=True)])
    def test_missing_instrument(self): self.good_with([{"id": "a", "type": "level", "direction": "below", "level": 1}])
    def test_bad_direction(self): self.good_with([lvl("sideways", 1, id="d")])
    def test_missing_direction(self): self.good_with([{"id": "a", "instrument": "X", "type": "level", "level": 1}])
    def test_unknown_type(self): self.good_with([{"id": "a", "instrument": "X", "type": "rsi", "direction": "below"}])
    def test_not_an_object(self): self.good_with([5, "x", None, [1]])
    def test_level_not_a_number(self): self.good_with([lvl("below", "abc", id="a"), lvl("below", None, id="b"), lvl("below", True, id="c")])
    def test_level_missing(self): self.good_with([{"id": "a", "instrument": "X", "type": "level", "direction": "below"}])
    def test_short_ge_long(self): self.good_with([ma("above", 20, 5, id="a"), ma("above", 5, 5, id="b")])
    def test_zero_or_negative_windows(self): self.good_with([ma("above", 0, 5, id="a"), ma("above", -1, 5, id="b")])
    def test_fractional_windows(self): self.good_with([ma("above", 2.5, 5, id="a")])
    def test_missing_windows(self): self.good_with([{"id": "a", "instrument": "X", "type": "ma_cross", "direction": "above"}])

    def test_nan_level_literal_in_json(self):
        raw = '[{"id":"a","instrument":"X","type":"level","direction":"below","level":NaN},' \
              '{"id":"ok","instrument":"X","type":"level","direction":"below","level":100}]'
        out, err = run_err(days("X", [110, 90]), raw)
        self.assertEqual(len(out), 1)
        self.assertIn("skipped", err)

    def test_lenient_but_unambiguous_inputs_accepted(self):
        out = run(days("X", [110, 90]), [
            {"id": "a", "instrument": "X", "type": "LEVEL", "direction": "Below", "level": "100"}])
        self.assertEqual(out, ["2026-09-02 a X level below 100"])
        raw = '[{"id":"m","instrument":"X","type":"ma_cross","direction":"above","short":2.0,"long":"3"}]'
        self.assertEqual(len(run(days("X", [10, 9, 8, 7, 9, 12]), raw)), 1)

    def test_extra_fields_ignored(self):
        r = lvl("below", 100, id="a")
        r.update({"note": "hello", "priority": 3})
        self.assertEqual(len(run(days("X", [110, 90]), [r])), 1)

    def test_empty_rules_list(self):
        self.assertEqual(run(days("X", [1, 2]), []), [])

    def test_rules_not_a_list(self):
        with self.assertRaises(ValueError):
            run(days("X", [1, 2]), '{"id":"a"}')

    def test_invalid_and_empty_json(self):
        for bad in ("{not json", ""):
            with self.assertRaises(ValueError):
                run(days("X", [1, 2]), bad)


# CLI
class CliTests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(HERE, "alerts.py"), *args],
                              capture_output=True, text=True)


    def test_rules_come_from_the_file_not_the_code(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(d, "p.csv", HEADER + "\n".join(days("X", [110, 90, 120, 80])) + "\n")
            r1 = _write(d, "a.json", json.dumps([lvl("below", 100, "X", "a")]))
            r2 = _write(d, "b.json", json.dumps([lvl("below", 100, "X", "a"), lvl("above", 100, "X", "b")]))
            r3 = _write(d, "c.json", "[]")
            out1 = self.cli(p, r1).stdout
            out2 = self.cli(p, r2).stdout
            out3 = self.cli(p, r3).stdout
            self.assertIn("2 alert(s)", out1)
            self.assertIn("3 alert(s)", out2)
            self.assertNotEqual(out1, out2)
            self.assertEqual(out3, "")

    def test_missing_file_clean_error(self):
        r = self.cli("nope.csv", "nope.json")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertNotIn("Traceback", r.stderr)

    def test_bad_input_files_clean_error(self):
        with tempfile.TemporaryDirectory() as d:
            good_p = _write(d, "p.csv", HEADER)
            for name, content in (("bad.json", "{not json"), ("empty.json", ""), ("obj.json", "{}")):
                r = self.cli(good_p, _write(d, name, content))
                self.assertEqual(r.returncode, 2, name)
                self.assertNotIn("Traceback", r.stderr)
            r = self.cli(_write(d, "empty.csv", ""), _write(d, "ok.json", "[]"))
            self.assertEqual(r.returncode, 2)
            bin_p = os.path.join(d, "bin.csv")
            with open(bin_p, "wb") as f:
                f.write(b"\xff\xfe\x00\x01\x80garbage")
            r = self.cli(bin_p, _write(d, "ok2.json", "[]"))
            self.assertEqual(r.returncode, 2)
            self.assertNotIn("Traceback", r.stderr)

    def test_usage(self):
        self.assertEqual(self.cli().returncode, 2)
        self.assertEqual(self.cli("only-one").returncode, 2)

    def test_warnings_on_stderr_alerts_on_stdout(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(d, "p.csv", HEADER + "2026-09-01,X,110\nbad,X,1\n2026-09-02,X,90\n")
            r = self.cli(p, _write(d, "r.json", json.dumps([lvl("below", 100)])))
            self.assertEqual(r.stdout, "X level: 1 alert(s) | latest alert: 2026-09-02\n")
            self.assertIn("warning", r.stderr)
            self.assertIn("1 warning", r.stderr)


    def test_clean_run_has_silent_stderr(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(d, "p.csv", HEADER + "2026-09-01,X,110\n2026-09-02,X,90\n")
            r = self.cli(p, _write(d, "r.json", json.dumps([lvl("below", 100)])))
            self.assertEqual(r.stderr, "")


if __name__ == "__main__":
    unittest.main()
