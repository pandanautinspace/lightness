I want a little puzzle to play in the terminal during builds: Lights Out. A 5×5 grid of lights;
pressing a light flips it and its neighbours up, down, left and right. You win when everything is
dark. Let me move around with the arrow keys and press with space (clicking with the mouse would
be nice too), count my moves, tell me when I've won, and give me a fresh puzzle when I ask.

## Contract

- `lights.py` defines `class LightsOutApp(textual.app.App)` with
  `__init__(self, board=None, seed=None)`; `python lights.py` runs it.
  - `board` is a list of 5 strings of 5 characters each, `#` = lit and `.` = dark, row by row
    from the top. When `board` is `None`, the app starts with a random puzzle drawn from
    `random.Random(seed)` (same seed ⇒ same puzzle).
- There are 25 cell widgets with ids `cell-R-C` (R = row 0–4 from the top, C = column 0–4 from
  the left). A lit cell has the CSS class `on`; a dark cell does not.
- A cursor starts on the top-left cell; the cell under it has the CSS class `cursor`. Arrow keys
  move it. `space` or `enter` presses the cell under the cursor; clicking a cell presses it.
  Pressing toggles that cell and its orthogonal neighbours (fewer at edges and corners).
- A widget with id `moves` shows the number of presses so far (a number).
- A widget with id `status`: once every light is dark it shows text containing the word
  "solved"; before that its text must not contain "solved".
- `n` starts a new random puzzle (from the same `Random` instance) and resets the move count to 0.
