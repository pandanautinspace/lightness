What the user wants but did not write down (answer questions only from this):

- Random puzzles must always be solvable (e.g. generate them by applying random presses to a
  dark board) and must never start already solved.
- Once the puzzle is solved the board is frozen: presses do nothing (and don't count) until a
  new puzzle is started with `n`.
- I want an undo: `u` takes back the last press (and the move count goes back down by one).
  Undo all the way to the start is fine; undo on a fresh puzzle does nothing.
- The cursor stops at the edges of the grid; it does not wrap around.
- No saving of games or scores is needed.
