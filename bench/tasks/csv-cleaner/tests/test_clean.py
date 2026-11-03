import csv
import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from lightness.bench.testkit import run_cli

FIXTURES = Path(__file__).parent / "fixtures"

# description -> (iso date, amount) after cleaning. Keys are compared after norm() so that how a
# solution tidies internal whitespace/case (an intent-level choice) can't cascade into these tests.
# Rows with ambiguous dates ("Parking garage" 04/03, "Erstattung Ärztin" 05.03) are checked only
# by intent tests; here they are only required to be present.
AMBIGUOUS_DATES = {"Parking garage", "Erstattung Ärztin"}
BANK_EXPECTED = {
    "Opening deposit": ("2024-03-01", 2000.00),
    "Payroll ACME Corp": ("2024-03-14", 1234.50),
    "Supermarkt REWE": ("2024-03-14", -12.00),
    "Electric bill": ("2024-03-13", -87.25),
    "Coffee Shop": ("2024-03-02", -4.50),
    "Bookstore": ("2024-03-02", -23.99),
    "Miete März": ("2024-03-20", -1250.00),
    "Refund Amazon": ("2024-03-25", 15.00),
    "ATM withdrawal": ("2024-03-28", -60.00),
    "Gym membership": ("2024-03-30", -29.99),
    "Interest": ("2024-03-31", 0.42),
    "Erstattung Ärztin": ("2024-03-05", 50.00),
}
GIRO_EXPECTED = {
    "Bäckerei Müller": ("2024-04-01", -3.50),
    "Laptop Kauf": ("2024-04-02", -1099.00),
    "Gehalt April": ("2024-04-03", 2500.00),
}


@pytest.fixture
def inputs(tmp_path: Path) -> Path:
    d = tmp_path / "in"
    shutil.copytree(FIXTURES, d)
    return d


def clean(src: Path, dst: Path, *flags: str):
    r = run_cli("clean.py", str(src), str(dst), *flags)
    assert r.returncode == 0, r.stderr
    return r


def clean_json(src: Path, dst: Path) -> dict:
    return json.loads(clean(src, dst, "--json").stdout)


def read_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    return rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]


def norm(desc: str) -> str:
    return " ".join(desc.split()).casefold()


def by_description(path: Path, normalize: bool = True) -> dict[str, list[tuple[str, float]]]:
    _, rows = read_rows(path)
    out: dict[str, list[tuple[str, float]]] = {}
    for d, desc, amount, *_ in rows:
        key = norm(desc) if normalize else desc
        out.setdefault(key, []).append((d.strip(), float(amount)))
    return out


def test_header_and_iso_dates(inputs, tmp_path):
    out = tmp_path / "clean.csv"
    clean(inputs / "bank_export.csv", out)
    header, rows = read_rows(out)
    assert [h.strip().lower() for h in header] == ["date", "description", "amount"]
    for row in rows:
        assert len(row) == 3
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[0]), row
        date.fromisoformat(row[0])


def test_dates_parsed_from_every_format(inputs, tmp_path):
    out = tmp_path / "clean.csv"
    clean(inputs / "bank_export.csv", out)
    got = by_description(out)
    for desc, (iso, _) in BANK_EXPECTED.items():
        assert norm(desc) in got, f"missing {desc!r}"
        if desc not in AMBIGUOUS_DATES:
            assert got[norm(desc)][0][0] == iso, desc


def test_currency_strings_become_signed_numbers(inputs, tmp_path):
    out = tmp_path / "clean.csv"
    clean(inputs / "bank_export.csv", out)
    got = by_description(out)
    for desc, (_, amount) in BANK_EXPECTED.items():
        assert norm(desc) in got, f"missing {desc!r}"
        assert got[norm(desc)][0][1] == pytest.approx(amount, abs=0.005), desc
    _, rows = read_rows(out)
    for row in rows:
        assert re.fullmatch(r"-?\d+(\.\d+)?", row[2].strip()), row


def test_duplicates_removed_and_whitespace_tidied(inputs, tmp_path):
    out = tmp_path / "clean.csv"
    report = clean_json(inputs / "bank_export.csv", out)
    got = by_description(out)
    assert all(len(v) == 1 for v in got.values()), got
    for desc in by_description(out, normalize=False):
        assert desc == desc.strip(), desc
    assert report["duplicates_removed"] == 3
    assert report["rows_written"] == 13 == sum(len(v) for v in got.values())


def test_unparseable_rows_skipped_and_counted(inputs, tmp_path):
    out = tmp_path / "clean.csv"
    report = clean_json(inputs / "bank_export.csv", out)
    got = by_description(out)
    assert "Card authorization" not in got and "Mystery charge" not in got
    assert report["skipped"] in (2, 3)  # the ",,," line may or may not count as a row


def test_summary_totals(inputs, tmp_path):
    report = clean_json(inputs / "bank_export.csv", tmp_path / "clean.csv")
    assert float(report["total_in"]) == pytest.approx(3299.92, abs=0.01)
    assert abs(float(report["total_out"])) == pytest.approx(1475.73, abs=0.01)


def test_plain_summary_and_input_untouched(inputs, tmp_path):
    src = inputs / "bank_export.csv"
    before = src.read_bytes()
    r = clean(src, tmp_path / "clean.csv")
    assert r.stdout.strip()
    assert src.read_bytes() == before


def test_semicolon_export_with_bom_and_shuffled_columns(inputs, tmp_path):
    out = tmp_path / "giro.csv"
    report = clean_json(inputs / "giro_export.csv", out)
    header, _ = read_rows(out)
    assert [h.strip().lower() for h in header] == ["date", "description", "amount"]
    got = by_description(out)
    assert set(got) == {norm(d) for d in GIRO_EXPECTED}
    for desc, (iso, amount) in GIRO_EXPECTED.items():
        rows = got[norm(desc)]
        assert len(rows) == 1 and rows[0][0] == iso, desc
        assert rows[0][1] == pytest.approx(amount, abs=0.005), desc
    assert report["rows_written"] == 3 and report["duplicates_removed"] == 1


def test_intent_slash_dates_are_us_format(inputs, tmp_path):
    out = tmp_path / "clean.csv"
    clean(inputs / "bank_export.csv", out)
    assert by_description(out)[norm("Parking garage")][0][0] == "2024-04-03"


def test_intent_dotted_dates_are_german(inputs, tmp_path):
    out = tmp_path / "clean.csv"
    clean(inputs / "bank_export.csv", out)
    assert by_description(out)[norm("Erstattung Ärztin")][0][0] == "2024-03-05"


def test_intent_descriptions_collapsed_and_deduplicated(inputs, tmp_path):
    out = tmp_path / "spacing.csv"
    report = clean_json(inputs / "spacing_export.csv", out)
    got = by_description(out, normalize=False)
    assert set(got) == {"Corner Store", "Train ticket", "Café Größe XL"}, got
    assert report["duplicates_removed"] == 1 and report["rows_written"] == 3
    for name in ("bank_export.csv", "giro_export.csv"):
        dst = tmp_path / f"clean-{name}"
        clean(inputs / name, dst)
        for desc in by_description(dst, normalize=False):
            assert desc == " ".join(desc.split()), desc
    assert "Payroll ACME Corp" in by_description(tmp_path / "clean-bank_export.csv", normalize=False)


def test_intent_sorted_oldest_first(inputs, tmp_path):
    out = tmp_path / "clean.csv"
    clean(inputs / "bank_export.csv", out)
    _, rows = read_rows(out)
    dates = [r[0] for r in rows]
    assert dates == sorted(dates)


def test_intent_amounts_have_two_decimals(inputs, tmp_path):
    for name in ("bank_export.csv", "giro_export.csv"):
        out = tmp_path / f"clean-{name}"
        clean(inputs / name, out)
        _, rows = read_rows(out)
        for row in rows:
            assert re.fullmatch(r"-?\d+\.\d{2}", row[2].strip()), row
