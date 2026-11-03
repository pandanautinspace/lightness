I keep jotting things into plain text files and I'm tired of opening a full editor for that.
Make me a tiny Textual notepad: open a text file (or a new one), edit it, save with ctrl+s.
Show me somewhere whether I have unsaved changes, and don't let me lose work by quitting
without asking first.

## Contract

- `notepad.py` defines `class NotepadApp(textual.app.App)` with `__init__(self, path)`;
  `python notepad.py FILE` runs it.
- A `TextArea` with id `editor` holds the file's text (UTF-8). A missing file means an empty
  editor; the file is created on first save, not before.
- `ctrl+s` saves the editor text to `path`.
- A widget with id `status` shows whether there are unsaved changes: its text contains the word
  "modified" when the editor differs from what was last loaded or saved, and does not contain
  "modified" otherwise.
- `ctrl+q` quits. With no unsaved changes it exits immediately. With unsaved changes it instead
  opens a `textual.screen.ModalScreen` with three `Button`s: id `save` (save, then exit), id
  `discard` (exit without saving), id `cancel` (close the dialog and keep editing; `escape` does
  the same).
