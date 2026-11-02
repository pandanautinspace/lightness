"""Search a folder of markdown notes: ranked full-text search plus tag filters."""

import argparse
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
INLINE_CODE = re.compile(r"`[^`\n]*`")
INLINE_TAG = re.compile(r"(?<![\w#/&])#([^\W\d][\w/-]*)")
WORD = re.compile(r"\w+")
TITLE_WEIGHT = 5


def fold(text: str) -> str:
    """Lowercase and strip accents so 'Café' matches 'cafe'."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def tokens(text: str) -> list[str]:
    return WORD.findall(fold(text))


def split_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    for end in range(1, len(lines)):
        if lines[end].strip() in ("---", "..."):
            break
    else:
        return {}, text
    meta: dict = {}
    key = None
    for line in lines[1:end]:
        item = re.match(r"\s+-\s*(.*)", line)
        if item and key:
            meta.setdefault(key, [])
            if isinstance(meta[key], list):
                meta[key].append(item.group(1).strip().strip("'\""))
            continue
        m = re.match(r"([\w-]+)\s*:\s*(.*)", line)
        if m:
            key, value = m.group(1).lower(), m.group(2).strip()
            meta[key] = value if value else []
    return meta, "\n".join(lines[end + 1:])


def parse_tag_list(value) -> list[str]:
    if isinstance(value, list):
        items = value
    else:
        items = re.split(r"[,\s]+", value.strip().strip("[]"))
    return [t.strip().strip("'\"").lstrip("#").lower() for t in items if t.strip().strip("'\"#")]


class Note:
    def __init__(self, root: Path, path: Path):
        text = path.read_text(encoding="utf-8", errors="replace")
        meta, body = split_front_matter(text)
        self.path = path.relative_to(root).as_posix()
        heading = re.search(r"^#\s+(.+)$", body, re.M)
        title = meta.get("title") if isinstance(meta.get("title"), str) else ""
        self.title = (title.strip("'\"") or (heading.group(1).strip() if heading else "") or path.stem)
        prose = INLINE_CODE.sub(" ", FENCE.sub(" ", body))
        inline = [t.lower() for t in INLINE_TAG.findall(prose)]
        self.tags = sorted(set(parse_tag_list(meta.get("tags", []))) | set(inline))
        self.title_terms = Counter(tokens(self.title))
        self.body_terms = Counter(tokens(body))
        self.length = sum(self.body_terms.values()) or 1

    def has(self, term: str) -> bool:
        return term in self.body_terms or term in self.title_terms


def load_notes(folder: Path) -> list[Note]:
    notes = []
    for path in sorted(folder.rglob("*.md")):
        rel = path.relative_to(folder)
        if any(part.startswith(".") for part in rel.parts) or not path.is_file():
            continue
        notes.append(Note(folder, path))
    return notes


def search(notes: list[Note], words: list[str], tags: list[str]) -> list[tuple[float, Note]]:
    terms = [t for w in words for t in tokens(w)]
    wanted = {t.lstrip("#").lower() for t in tags}
    hits = [n for n in notes if wanted <= set(n.tags) and all(n.has(t) for t in terms)]
    results = []
    for note in hits:
        score = 0.0
        for term in set(terms):
            df = sum(1 for n in notes if n.has(term))
            idf = math.log(1 + len(notes) / df)
            tf = note.body_terms[term] / math.sqrt(note.length)
            score += idf * (tf + TITLE_WEIGHT * note.title_terms[term])
        results.append((round(score, 4), note))
    results.sort(key=lambda r: (-r[0], r[1].path))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("search", help="search notes")
    s.add_argument("folder", type=Path)
    s.add_argument("words", nargs="*")
    s.add_argument("--tag", action="append", default=[], help="only notes with this tag (repeatable)")
    s.add_argument("--json", action="store_true")
    t = sub.add_parser("tags", help="list tags with note counts")
    t.add_argument("folder", type=Path)
    t.add_argument("--json", action="store_true")
    args = parser.parse_args()

    notes = load_notes(args.folder.resolve())
    if args.command == "tags":
        counts = Counter(tag for n in notes for tag in n.tags)
        if args.json:
            print(json.dumps(dict(sorted(counts.items())), ensure_ascii=False))
        else:
            for tag, n in counts.most_common():
                print(f"#{tag}  {n}")
        return

    if not args.words and not args.tag:
        parser.error("give some words to search for and/or --tag")
    results = search(notes, args.words, args.tag)
    if args.json:
        out = [{"path": n.path, "title": n.title, "tags": n.tags, "score": s} for s, n in results]
        print(json.dumps(out, ensure_ascii=False))
        return
    for score, n in results:
        tags = " ".join("#" + t for t in n.tags)
        print(f"{score:7.2f}  {n.path}  — {n.title}  {tags}")
    if not results:
        print("no matches")


if __name__ == "__main__":
    main()
