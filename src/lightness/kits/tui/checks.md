## Checks

`checks.txt` holds the task's contract as checks. After every change the harness runs each one in
a fresh app and tells you which fail, and which passed before and fail now. One check per line:

    NAME: [--file-text PARAM=TEXT ...] STEP ...

The steps are the try command's (`type:`, `press:`, `focus:`, `click:`, `advance:`, `restart`),
plus three that check what is there at that point:

- `expect:TEXT`: TEXT is on the screen, as the try command prints it (a row, a label, a notification).
- `expect-not:TEXT`: TEXT is not on the screen.
- `expect-file:PARAM=TEXT`: the data file PARAM holds exactly TEXT (JSON is compared as values).

Quote a step that has spaces: `expect:"total: 3"`. Lines starting with `#` are comments. Example,
for an app whose data parameter is `{data}`:

    add an item: focus:#name type:milk press:enter expect:"milk" expect-file:{data}='[{"name": "milk"}]'
    kept after restart: --file-text {data}='[{"name": "milk"}]' restart expect:"milk"

Write one check per contract item: each key and what it does, the saved file's exact format,
starting with no data file and with existing data, and wrong input. Take the expected values
from the task. The harness already checks on its own that every key works without crashing (with
and without a data file), that a start keeps the saved file, and that time can move: don't
write checks for those.

Run them yourself with `python .lightness/kit/try_app.py --checks checks.txt`. When a check
fails, fix the app; change the check only if it disagrees with the task, and then edit that one
line (e.g. with sed) instead of writing the file again. A submit is refused once while checks fail.