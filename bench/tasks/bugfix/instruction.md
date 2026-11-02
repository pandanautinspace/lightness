I've been using my little notes app (this repo) for a while and something is off. When I page
through my notes from the API, some of them never show up, and on the last page I sometimes get
notes I already saw on the page before. It doesn't happen all the time, and I think it got
worse once I had more notes than fit on one page. Search results seem to have the same problem.

Can you find out what's going on and fix it? Please don't break anything else, the existing
tests should keep passing.

## Contract

- Keep the existing API, CLI and `create_app(db_path)` factory as they are; only fix the bug.
- Use only the Python standard library and Flask.
