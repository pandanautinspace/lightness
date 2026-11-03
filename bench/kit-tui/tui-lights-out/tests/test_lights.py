import asyncio
import re

from lightness.bench.testkit import import_from_workspace

ONE_PRESS_CENTER = [".....", "..#..", ".###.", "..#..", "....."]
ONE_PRESS_CORNER = ["##...", "#....", ".....", ".....", "....."]


def text_of(widget) -> str:
    parts = []
    for node in [widget, *widget.query("*")]:
        value = getattr(node, "value", None)
        if isinstance(value, str):
            parts.append(value)
        try:
            parts.append(str(node.render()))
        except Exception:
            pass
    return " ".join(parts)


def run(scenario, board=None, seed=None):
    lights = import_from_workspace("lights")

    async def main():
        app = lights.LightsOutApp(board=board, seed=seed)
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.pause()
            result = await scenario(app, pilot)
            await pilot.pause()
            return result

    return asyncio.run(main())


def grid(app) -> list[str]:
    return ["".join("#" if app.query_one(f"#cell-{r}-{c}").has_class("on") else "." for c in range(5))
            for r in range(5)]


def cursor(app):
    hits = [(r, c) for r in range(5) for c in range(5) if app.query_one(f"#cell-{r}-{c}").has_class("cursor")]
    assert len(hits) == 1, hits
    return hits[0]


def moves(app) -> int:
    nums = re.findall(r"\d+", text_of(app.query_one("#moves")))
    assert nums, text_of(app.query_one("#moves"))
    return int(nums[0])


def says_solved(app) -> bool:
    return "solved" in text_of(app.query_one("#status")).lower()


async def go_to(pilot, r, c):
    cr, cc = cursor(pilot.app)
    keys = (["down"] * (r - cr) if r > cr else ["up"] * (cr - r)) + \
           (["right"] * (c - cc) if c > cc else ["left"] * (cc - c))
    if keys:
        await pilot.press(*keys)
    await pilot.pause()
    assert cursor(pilot.app) == (r, c)


async def press_at(pilot, r, c, key="space"):
    await go_to(pilot, r, c)
    await pilot.press(key)
    await pilot.pause()


def solvable(board: list[str]) -> bool:
    """Gaussian elimination over GF(2) for the 5x5 Lights Out system."""
    rows = []
    for r in range(5):
        for c in range(5):
            mask = 0
            for dr, dc in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                rr, cc = r + dr, c + dc
                if 0 <= rr < 5 and 0 <= cc < 5:
                    mask |= 1 << (rr * 5 + cc)
            rows.append([mask, 1 if board[r][c] == "#" else 0])
    pivot_row = 0
    for col in range(25):
        sel = next((i for i in range(pivot_row, 25) if rows[i][0] >> col & 1), None)
        if sel is None:
            continue
        rows[pivot_row], rows[sel] = rows[sel], rows[pivot_row]
        for i in range(25):
            if i != pivot_row and rows[i][0] >> col & 1:
                rows[i][0] ^= rows[pivot_row][0]
                rows[i][1] ^= rows[pivot_row][1]
        pivot_row += 1
    return all(not (m == 0 and b) for m, b in rows)


def test_cells_reflect_given_board():
    board = ["#....", ".#...", "..#..", "...#.", "....#"]

    async def scenario(app, pilot):
        assert grid(app) == board
        assert cursor(app) == (0, 0)
        assert moves(app) == 0
        assert not says_solved(app)

    run(scenario, board=board)


def test_press_center_flips_plus_shape():
    async def scenario(app, pilot):
        await press_at(pilot, 2, 2)
        assert grid(app) == [".....", "..#..", ".###.", "..#..", "#...."]
        assert moves(app) == 1

    run(scenario, board=["....."] * 4 + ["#...."])


def test_press_corner_and_edge():
    async def scenario(app, pilot):
        await press_at(pilot, 0, 0)
        assert grid(app) == ["##...", "#....", ".....", ".....", "....#"]
        await press_at(pilot, 4, 2)
        assert grid(app) == ["##...", "#....", ".....", "..#..", ".####"]

    run(scenario, board=["....."] * 4 + ["....#"])


def test_arrow_keys_move_cursor():
    async def scenario(app, pilot):
        await pilot.press("right", "right", "down")
        await pilot.pause()
        assert cursor(app) == (1, 2)
        await pilot.press("left", "up")
        await pilot.pause()
        assert cursor(app) == (0, 1)
        assert grid(app)[0] == "#...."  # moving doesn't press

    run(scenario, board=["#...."] + ["....."] * 4)


def test_enter_also_presses_and_moves_count():
    async def scenario(app, pilot):
        await press_at(pilot, 1, 1, key="enter")
        await press_at(pilot, 3, 3, key="space")
        await press_at(pilot, 3, 3, key="space")
        assert moves(app) == 3
        assert grid(app) == ["##...", "###..", ".#...", ".....", "....."]

    run(scenario, board=["#...."] + ["....."] * 4)


def test_solving_shows_solved():
    async def scenario(app, pilot):
        assert not says_solved(app)
        await press_at(pilot, 1, 2)
        assert not says_solved(app)
        await press_at(pilot, 1, 2)
        await press_at(pilot, 2, 2)
        assert grid(app) == ["....."] * 5
        assert says_solved(app)
        assert moves(app) == 3

    run(scenario, board=ONE_PRESS_CENTER)


def test_click_presses_cell():
    async def scenario(app, pilot):
        await pilot.click("#cell-0-0")
        await pilot.pause()
        assert grid(app) == ["....."] * 5
        assert says_solved(app)
        assert moves(app) == 1

    run(scenario, board=ONE_PRESS_CORNER)


def test_seeded_random_puzzle_is_deterministic():
    boards = [run(lambda app, pilot: asyncio.sleep(0, grid(app)), seed=s) for s in (7, 7, 8)]
    assert boards[0] == boards[1]
    assert boards[0] != ["....."] * 5
    assert all(len(b) == 5 and all(len(r) == 5 for r in b) for b in boards)


def test_new_puzzle_resets_moves():
    async def scenario(app, pilot):
        await press_at(pilot, 2, 2)
        assert says_solved(app)
        await pilot.press("n")
        await pilot.pause()
        assert moves(app) == 0
        assert grid(app) != ["....."] * 5
        assert not says_solved(app)
        assert cursor(app) in [(r, c) for r in range(5) for c in range(5)]

    run(scenario, board=ONE_PRESS_CENTER, seed=3)


def test_intent_random_puzzles_are_solvable():
    async def scenario(app, pilot):
        seen = [grid(app)]
        for _ in range(5):
            await pilot.press("n")
            await pilot.pause()
            seen.append(grid(app))
        return seen

    for seed in (1, 2, 3):
        for board in run(scenario, seed=seed):
            assert board != ["....."] * 5
            assert solvable(board), board


def test_intent_frozen_after_solve():
    async def scenario(app, pilot):
        await press_at(pilot, 2, 2)
        assert says_solved(app)
        await pilot.press("space")
        await pilot.pause()
        await pilot.click("#cell-4-4")
        await pilot.pause()
        assert grid(app) == ["....."] * 5
        assert moves(app) == 1
        assert says_solved(app)

    run(scenario, board=ONE_PRESS_CENTER)


def test_intent_undo_last_press():
    board = ["#...."] + ["....."] * 4

    async def scenario(app, pilot):
        await pilot.press("u")  # nothing to undo
        await pilot.pause()
        assert grid(app) == board and moves(app) == 0
        await press_at(pilot, 1, 1)
        await press_at(pilot, 3, 3)
        await pilot.press("u")
        await pilot.pause()
        assert moves(app) == 1
        assert grid(app) == ["##...", "###..", ".#...", ".....", "....."]
        await pilot.press("u")
        await pilot.pause()
        assert moves(app) == 0
        assert grid(app) == board

    run(scenario, board=board)
