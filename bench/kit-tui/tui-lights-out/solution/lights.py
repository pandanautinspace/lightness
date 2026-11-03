"""Lights Out in the terminal."""

import random

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid
from textual.widgets import Footer, Header, Static

SIZE = 5


class Cell(Static):
    def __init__(self, r: int, c: int):
        super().__init__(" ", id=f"cell-{r}-{c}")
        self.r, self.c = r, c

    def on_click(self) -> None:
        self.app.press_cell(self.r, self.c)


class LightsOutApp(App):
    TITLE = "Lights Out"
    CSS = """
    Grid { grid-size: 5 5; grid-gutter: 0 1; width: 39; height: 15; margin: 1 2; }
    Cell { width: 7; height: 3; background: $panel; content-align: center middle; }
    Cell.on { background: $warning; }
    Cell.cursor { border: round $accent; }
    #moves, #status { margin: 0 2; }
    """
    BINDINGS = [
        Binding("up", "move(-1, 0)", "Up", show=False),
        Binding("down", "move(1, 0)", "Down", show=False),
        Binding("left", "move(0, -1)", "Left", show=False),
        Binding("right", "move(0, 1)", "Right", show=False),
        Binding("space", "press_cursor", "Press"),
        Binding("enter", "press_cursor", "Press", show=False),
        Binding("u", "undo", "Undo"),
        Binding("n", "new_game", "New puzzle"),
    ]

    def __init__(self, board=None, seed=None):
        super().__init__()
        self.rng = random.Random(seed)
        if board is None:
            self.lights = self.random_board()
        else:
            self.lights = [[ch == "#" for ch in row] for row in board]
        self.cursor = (0, 0)
        self.history: list[tuple[int, int]] = []

    def random_board(self) -> list[list[bool]]:
        while True:
            self.lights = [[False] * SIZE for _ in range(SIZE)]
            for _ in range(self.rng.randint(5, 15)):
                self.toggle(self.rng.randrange(SIZE), self.rng.randrange(SIZE))
            if not self.solved:
                return self.lights

    @property
    def solved(self) -> bool:
        return not any(any(row) for row in self.lights)

    def compose(self) -> ComposeResult:
        yield Header()
        with Grid():
            for r in range(SIZE):
                for c in range(SIZE):
                    yield Cell(r, c)
        yield Static(id="moves")
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.redraw()

    def toggle(self, r: int, c: int) -> None:
        for dr, dc in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            rr, cc = r + dr, c + dc
            if 0 <= rr < SIZE and 0 <= cc < SIZE:
                self.lights[rr][cc] = not self.lights[rr][cc]

    def press_cell(self, r: int, c: int) -> None:
        if self.solved:
            return
        self.toggle(r, c)
        self.history.append((r, c))
        self.redraw()

    def redraw(self) -> None:
        for cell in self.query(Cell):
            cell.set_class(self.lights[cell.r][cell.c], "on")
            cell.set_class((cell.r, cell.c) == self.cursor, "cursor")
        self.query_one("#moves", Static).update(f"Moves: {len(self.history)}")
        status = "Solved! Press n for a new puzzle." if self.solved else "Turn all the lights off."
        self.query_one("#status", Static).update(status)

    def action_move(self, dr: int, dc: int) -> None:
        r, c = self.cursor
        self.cursor = (min(max(r + dr, 0), SIZE - 1), min(max(c + dc, 0), SIZE - 1))
        self.redraw()

    def action_press_cursor(self) -> None:
        self.press_cell(*self.cursor)

    def action_undo(self) -> None:
        if self.history and not self.solved:
            self.toggle(*self.history.pop())
            self.redraw()

    def action_new_game(self) -> None:
        self.lights = self.random_board()
        self.history = []
        self.cursor = (0, 0)
        self.redraw()


if __name__ == "__main__":
    LightsOutApp().run()
