"""Part: a grid of cells driven by keys (board games, simulations).

- Keep the board as plain data (list of lists) and the game rules in plain methods (move,
  toggle, step, winner) that tests can call directly; widgets only draw the board.
- Lay out cells with CSS `layout: grid; grid-size: <cols> <rows>;` and give each cell an id
  like "cell-<row>-<col>". A key-driven cursor avoids depending on mouse clicks.
- Randomness: take a seed or a random.Random in __init__ so games are reproducible.
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid
from textual.widgets import Static

SIZE = 3


class LightsApp(App):
    CSS = f"""
    #board {{ layout: grid; grid-size: {SIZE} {SIZE}; width: {SIZE * 6}; height: {SIZE * 3}; }}
    .cell {{ border: round $secondary; content-align: center middle; }}
    .cell.on {{ background: $warning; }}
    .cell.cursor {{ border: heavy $accent; }}
    """
    BINDINGS = [
        Binding("up", "move(-1, 0)", "Up"),
        Binding("down", "move(1, 0)", "Down"),
        Binding("left", "move(0, -1)", "Left"),
        Binding("right", "move(0, 1)", "Right"),
        Binding("space", "press", "Toggle"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.board = [[False] * SIZE for _ in range(SIZE)]
        self.cursor = (0, 0)
        self.moves = 0

    def compose(self) -> ComposeResult:
        with Grid(id="board"):
            for r in range(SIZE):
                for c in range(SIZE):
                    yield Static("", id=f"cell-{r}-{c}", classes="cell")
        yield Static("", id="status")

    def on_mount(self) -> None:
        self.refresh_view()

    def toggle(self, r: int, c: int) -> None:
        for dr, dc in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            if 0 <= r + dr < SIZE and 0 <= c + dc < SIZE:
                self.board[r + dr][c + dc] = not self.board[r + dr][c + dc]

    def won(self) -> bool:
        return all(all(row) for row in self.board)

    def refresh_view(self) -> None:
        for r in range(SIZE):
            for c in range(SIZE):
                cell = self.query_one(f"#cell-{r}-{c}", Static)
                cell.set_class(self.board[r][c], "on")
                cell.set_class((r, c) == self.cursor, "cursor")
        status = "You win!" if self.won() else f"Moves: {self.moves}"
        self.query_one("#status", Static).update(status)

    def action_move(self, dr: int, dc: int) -> None:
        r, c = self.cursor
        self.cursor = (min(max(r + dr, 0), SIZE - 1), min(max(c + dc, 0), SIZE - 1))
        self.refresh_view()

    def action_press(self) -> None:
        if not self.won():
            self.toggle(*self.cursor)
            self.moves += 1
            self.refresh_view()


if __name__ == "__main__":
    LightsApp().run()
