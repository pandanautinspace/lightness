"""Sort a folder's top-level files into category subfolders. Dry run unless --apply."""

import argparse
import json
import shutil
from pathlib import Path

CATEGORIES = {
    "Images": "jpg jpeg png gif webp heic",
    "Documents": "pdf doc docx txt md rtf odt xls xlsx csv ppt pptx",
    "Archives": "zip tar gz tgz rar 7z",
    "Audio": "mp3 wav flac m4a ogg",
    "Video": "mp4 mov mkv avi webm",
    "Code": "py js ts html css json sh",
}
EXT_TO_CATEGORY = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts.split()}


def category_for(path: Path) -> str:
    category = EXT_TO_CATEGORY.get(path.suffix.lower().lstrip("."), "Other")
    if category == "Images" and path.name.lower().startswith("screenshot"):
        return "Screenshots"
    return category


def free_name(dest_dir: Path, name: str, taken: set[Path]) -> Path:
    candidate = dest_dir / name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while candidate.exists() or candidate in taken:
        candidate = dest_dir / f"{stem} ({n}){suffix}"
        n += 1
    return candidate


def plan(folder: Path) -> list[tuple[Path, Path]]:
    moves, taken = [], set()
    for path in sorted(folder.iterdir()):
        if path.name.startswith(".") or not path.is_file() or path.is_symlink():
            continue
        dest = free_name(folder / category_for(path), path.name, taken)
        taken.add(dest)
        moves.append((path, dest))
    return moves


def apply(moves: list[tuple[Path, Path]]) -> None:
    for src, dst in moves:
        dst.parent.mkdir(exist_ok=True)
        shutil.move(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--apply", action="store_true", help="perform the moves")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = parser.parse_args()

    folder = args.folder.resolve()
    moves = plan(folder)
    if args.json:
        print(json.dumps([{"src": str(s.relative_to(folder)), "dst": str(d.relative_to(folder))} for s, d in moves]))
    else:
        for s, d in moves:
            print(f"{s.relative_to(folder)} -> {d.relative_to(folder)}")
        print(f"{len(moves)} file(s) {'moved' if args.apply else 'would be moved (dry run; use --apply)'}")
    if args.apply:
        apply(moves)


if __name__ == "__main__":
    main()
