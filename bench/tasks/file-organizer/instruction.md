My Downloads folder is a mess. Write a small tool that tidies a folder by sorting its files
into subfolders by type. I'm nervous about it moving things around, so by default it should
only show me what it *would* do, and I want to be sure it never loses or overwrites anything.

## Contract

- Entry point: `python organize.py FOLDER` prints the plan and changes nothing.
- `python organize.py FOLDER --apply` actually moves the files.
- `python organize.py FOLDER --json` prints the plan as a JSON list of
  `{"src": ..., "dst": ...}` objects with paths relative to FOLDER (no changes made).
  `--json --apply` prints the same list and performs the moves.
- Use only the Python standard library.
