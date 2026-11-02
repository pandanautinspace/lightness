I keep all my notes as markdown files in one folder (with some subfolders), Obsidian-style.
Finding things has become painful. I'd like a little command-line tool that indexes the
folder and lets me search it: best matches first, and I want to narrow things down by tag.
I tag notes either with `#tags` in the text or in the YAML front matter at the top (`tags:`),
depending on my mood. Some notes are in German or have accents, so unicode should just work.

## Contract

- `python notes.py search FOLDER [WORDS ...] [--tag TAG ...] [--json]` searches every `*.md`
  file under FOLDER (including subfolders) and prints the matching notes, best match first.
  `WORDS` may be left out when at least one `--tag` is given.
- With `--json`, print a JSON list (best match first, `[]` if nothing matches) of objects with
  at least: `path` (relative to FOLDER, `/`-separated), `title`, `tags` (list of tag names
  without the `#`) and `score` (a number; higher is better).
- `python notes.py tags FOLDER --json` prints a JSON object mapping each tag name to the number
  of notes that have it.
- Results must always reflect the current files, even if you keep an index on disk.
- Use only the Python standard library.
