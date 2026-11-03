My browser bookmarks are a mess across three machines, so I want to keep the ones that matter in
one place I can reach over ssh. Make me a Textual bookmark manager: a list of my bookmarks that I
can search, add new ones (title, URL, a few tags) in a little pop-up form, fix ones I got wrong,
and delete the dead ones. Keep everything in a SQLite file.

## Contract

- `bookmarks.py` defines `class BookmarksApp(textual.app.App)` with `__init__(self, db_path)`;
  `python bookmarks.py [DB]` runs it (default `bookmarks.db`).
- Data lives in the SQLite file at `db_path`, table `bookmarks` with (at least) the columns
  `id INTEGER PRIMARY KEY`, `title TEXT`, `url TEXT`, `tags TEXT` (tags comma-separated, empty
  string for none). The app creates the table if it doesn't exist; if it already exists with just
  those four columns, the app uses it as-is. Every change is committed immediately.
- A `ListView` with id `bookmark-list` with one `ListItem` per bookmark currently shown, which
  displays the bookmark's title.
- An `Input` with id `search`: the list shows only bookmarks whose title, URL or tags contain
  the text, case-insensitively (empty = all).
- Keys while the list has focus: `a` opens the add dialog, `e` opens the edit dialog for the
  highlighted bookmark, `d` deletes the highlighted bookmark.
- The add/edit dialog is a `textual.screen.ModalScreen` with `Input`s with ids `bm-title`,
  `bm-url`, `bm-tags` (edit pre-fills them with the bookmark's current values; tags shown as
  comma-separated text) and `Button`s with ids `bm-save` and `bm-cancel`. Saving (the button, or
  pressing enter in any of the inputs) stores the bookmark and closes the dialog; `bm-cancel` or
  `escape` closes it without changing anything. Saving with an empty URL does nothing: the dialog
  stays open and nothing is stored.
