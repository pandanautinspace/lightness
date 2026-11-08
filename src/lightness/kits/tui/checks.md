## Checks

Your first file is `checks.txt` (it doesn't exist yet: create it before any app code). It holds the
task's contract as checks. After every change the harness runs each one in a fresh app and tells
you which fail, and which passed before and fail now.

Each line is one whole check: a short name, a colon, then everything that check does (its file or
App options, its steps and its expects) on that same line:

    NAME: [--file-text PARAM=TEXT ...] [--kw NAME=VALUE ...] STEP ...

    counter starts at zero: expect:"count: 0"
    plus adds one: press:plus expect:"count: 1"
    plus twice from 5: --kw start=5 press:plus,plus expect:"count: 7"

Not a script spread over lines: a line without `NAME:` in front, or with only an option, is an error.

`--kw NAME=VALUE` passes an App argument that isn't a file, as a Python literal: `--kw seed=1`,
`--kw "size=3"`, `--kw "items=['a', 'b']"` (quote a value with spaces or brackets).

The steps are the try command's (`type:`, `press:`, `focus:`, `click:`, `advance:`, `restart`),
plus three that check what is there at that point:

- `expect:TEXT`: TEXT is on the screen, as the try command prints it (a row, a label, a notification).
- `expect-not:TEXT`: TEXT is not on the screen.
- `expect-file:PARAM=TEXT`: the data file PARAM holds exactly TEXT (JSON is compared as values).

Quote a step that has spaces: `expect:"total: 3"`. Lines starting with `#` are comments.

`expect:` matches any part of the screen, so `expect:"$.a"` also passes when the widget shows `Path: $.a`.
When the task gives a widget's exact text, check all of it the way the screen prints it, id and quotes
included: `expect:"#path: '$.a'"` passes only if #path shows exactly `$.a`.

{example}

Each check is independent: it starts a fresh app, with no records unless its own steps add them
(or it gives a file), so a check never sees what another check did. A check that needs a record
adds it first, in its own steps.

Write one check per contract item: each key and what it does, the saved file's exact format,
starting with no data file and with existing data, and wrong input. Take the expected values
from the task. The harness already checks on its own that every key works without crashing (with
and without a data file), that a start keeps the saved file, and that time can move: don't
write checks for those.

You don't need to run them yourself: the harness reports after every change. When a check
fails, fix the app; change the check only if it disagrees with the task, and then edit that one
line (e.g. with sed) instead of writing the file again. A submit is refused once while checks fail.