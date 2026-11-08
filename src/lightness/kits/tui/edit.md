## Changing a file

Write a file whole only the first time. After that, change just the part that needs it with the
`edit_file` tool instead of writing the whole file again: a rewrite takes minutes, and it can drop
or repeat code you didn't mean to touch.

`edit_file` takes `path`, `old_text` (copied exactly from the file, a few whole lines, spaces
included) and `new_text`. old_text must occur exactly once: if it doesn't, nothing changes and the
reply shows the closest lines. To add code, use the line next to where it goes as old_text and put
that line plus the new ones in new_text. One call per place to change; several calls can go in one
response. It works the same for a line of checks.txt.
