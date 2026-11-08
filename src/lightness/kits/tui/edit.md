## Changing a file

Write a file whole only the first time. After that, change just the lines that need it with the
edit command instead of writing the whole file again: a rewrite takes minutes, and it can drop or
repeat code you didn't mean to touch.

    python .lightness/kit/edit.py FILE <<'EOF'
    <<<<<<< SEARCH
    the lines now in the file, copied exactly (a few whole lines)
    =======
    the lines to put there instead
    >>>>>>> REPLACE
    EOF

Several SEARCH/REPLACE blocks can follow each other in one command (one per place to change). Each
SEARCH must match exactly one place in the file: if one doesn't, nothing changes and the command
shows the closest lines. To add code, SEARCH for the line next to where it goes and REPLACE it with
that line plus the new ones. The same works for a line of checks.txt.
