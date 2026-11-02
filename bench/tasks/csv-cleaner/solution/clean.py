"""Clean a messy bank-export CSV into date,description,amount and print a short summary."""

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

DATE_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d.%m.%Y", "%b %d, %Y", "%B %d, %Y",
    "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y", "%m/%d/%y", "%d.%m.%y",
]
COLUMNS = ("date", "description", "amount")


def parse_date(text: str) -> date | None:
    text = " ".join(text.split())
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def parse_amount(text: str) -> Decimal | None:
    s = text.strip().replace(" ", " ")
    if not s:
        return None
    euro = "€" in s or "EUR" in s.upper()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    s = re.sub(r"(?i)[$€]|usd|eur|\s", "", s)
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.startswith("-"):
        negative, s = not negative, s[1:]
    elif s.startswith("+"):
        s = s[1:]
    if s.endswith("-"):  # some banks write "12.00-"
        negative, s = not negative, s[:-1]
    if euro or re.fullmatch(r"\d{1,3}(\.\d{3})*,\d{1,2}|\d+,\d{1,2}", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative else value


def read_table(path: Path) -> list[list[str]]:
    text = path.read_text(encoding="utf-8-sig")
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = ";" if first.count(";") > first.count(",") else ","
    return [row for row in csv.reader(text.splitlines(), delimiter=delimiter)]


def find_columns(header: list[str]) -> dict[str, int]:
    names = [h.strip().lower() for h in header]
    found = {}
    for col in COLUMNS:
        for i, name in enumerate(names):
            if col in name and i not in found.values():
                found[col] = i
                break
        else:
            sys.exit(f"no {col!r} column in header {header}")
    return found


def clean(src: Path, dst: Path) -> dict:
    rows = [r for r in read_table(src) if any(c.strip() for c in r)]
    cols = find_columns(rows[0])
    kept, seen = [], set()
    dupes = skipped = 0
    for row in rows[1:]:
        cells = [row[cols[c]] if cols[c] < len(row) else "" for c in COLUMNS]
        d, amount = parse_date(cells[0]), parse_amount(cells[2])
        desc = " ".join(cells[1].split())
        if d is None or amount is None:
            skipped += 1
            continue
        key = (d, desc, amount)
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        kept.append(key)
    kept.sort(key=lambda r: r[0])  # stable: same-day rows keep input order

    with dst.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for d, desc, amount in kept:
            w.writerow([d.isoformat(), desc, f"{amount:.2f}"])

    money_in = sum((a for _, _, a in kept if a > 0), Decimal(0))
    money_out = sum((a for _, _, a in kept if a < 0), Decimal(0))
    return {
        "rows_read": len(rows) - 1,
        "rows_written": len(kept),
        "duplicates_removed": dupes,
        "skipped": skipped,
        "total_in": float(money_in),
        "total_out": float(money_out),
        "net": float(money_in + money_out),
        "first_date": kept[0][0].isoformat() if kept else None,
        "last_date": kept[-1][0].isoformat() if kept else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args()

    report = clean(args.input, args.output)
    if args.json:
        print(json.dumps(report))
        return
    print(f"Wrote {report['rows_written']} of {report['rows_read']} rows to {args.output}")
    print(f"  duplicates removed: {report['duplicates_removed']}")
    print(f"  skipped (unreadable date/amount): {report['skipped']}")
    if report["first_date"]:
        print(f"  period: {report['first_date']} .. {report['last_date']}")
    print(f"  money in:  {report['total_in']:>12,.2f}")
    print(f"  money out: {report['total_out']:>12,.2f}")
    print(f"  net:       {report['net']:>12,.2f}")


if __name__ == "__main__":
    main()
