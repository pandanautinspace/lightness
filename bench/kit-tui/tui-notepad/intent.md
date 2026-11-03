What the user wants but did not write down (answer questions only from this):

- Before each save overwrites an existing file, the previous contents are copied to a backup
  next to it with `.bak` appended to the full name (`notes.txt` → `notes.txt.bak`). Only the
  most recent backup is kept.
- Saved files always end with a newline (add one if the text doesn't end with one), so tools
  like `cat` and git don't complain.
- The file name is shown somewhere (title bar or status line).
- No autosave; I save when I want to.
- Opening a file must not change it on disk.
