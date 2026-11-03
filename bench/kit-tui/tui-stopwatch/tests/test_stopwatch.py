import asyncio
import re

from lightness.bench.testkit import import_from_workspace

TIME = re.compile(r"(?:\d+:)?\d\d:\d\d\.\d")


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


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


def run(scenario):
    sw = import_from_workspace("stopwatch")
    clock = FakeClock()

    async def main():
        app = sw.StopwatchApp(clock=clock)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            result = await scenario(app, pilot, clock)
            await pilot.pause()
            return result

    return asyncio.run(main())


async def settle(pilot):
    await pilot.pause(0.35)


def shown(app) -> str:
    """The time currently displayed in #elapsed."""
    found = TIME.findall(text_of(app.query_one("#elapsed")))
    assert found, text_of(app.query_one("#elapsed"))
    return found[0]


def laps(app) -> list[str]:
    from textual.widgets import ListItem

    return [text_of(item) for item in app.query_one("#laps").query(ListItem)]


async def key(pilot, *keys):
    await pilot.press(*keys)
    await settle(pilot)


def test_starts_at_zero():
    async def scenario(app, pilot, clock):
        from textual.widgets import ListView

        assert isinstance(app.query_one("#laps"), ListView)
        clock.t += 50
        await settle(pilot)
        assert shown(app) == "00:00.0"
        assert laps(app) == []

    run(scenario)


def test_runs_and_refreshes_by_itself():
    async def scenario(app, pilot, clock):
        await key(pilot, "space")
        seen = []
        for step in (1.3125, 2.125, 1.875):
            clock.t += step
            await settle(pilot)
            seen.append(shown(app))
        assert seen == ["00:01.3", "00:03.4", "00:05.3"]

    run(scenario)


def test_minutes_format():
    async def scenario(app, pilot, clock):
        await key(pilot, "space")
        clock.t += 65.3125
        await settle(pilot)
        assert shown(app) == "01:05.3"
        clock.t += 534.75
        await settle(pilot)
        assert shown(app) == "10:00.0"

    run(scenario)


def test_pause_freezes_and_resume_continues():
    async def scenario(app, pilot, clock):
        await key(pilot, "space")
        clock.t += 3.0625
        await key(pilot, "space")
        assert shown(app) == "00:03.0"
        clock.t += 100
        await settle(pilot)
        assert shown(app) == "00:03.0"
        await key(pilot, "space")
        clock.t += 2.125
        await settle(pilot)
        assert shown(app) == "00:05.1"

    run(scenario)


def test_lap_adds_entry():
    async def scenario(app, pilot, clock):
        await key(pilot, "space")
        clock.t += 5.3125
        await key(pilot, "l")
        rows = laps(app)
        assert len(rows) == 1
        assert "00:05.3" in rows[0]

    run(scenario)


def test_lap_ignored_when_not_running():
    async def scenario(app, pilot, clock):
        await key(pilot, "l")
        assert laps(app) == []
        await key(pilot, "space")
        clock.t += 2.0625
        await key(pilot, "l")
        await key(pilot, "space")
        await key(pilot, "l")
        assert len(laps(app)) == 1

    run(scenario)


def test_reset_when_paused_clears_everything():
    async def scenario(app, pilot, clock):
        await key(pilot, "space")
        clock.t += 4.0625
        await key(pilot, "l")
        clock.t += 1.0625
        await key(pilot, "l")
        await key(pilot, "space")
        await key(pilot, "r")
        assert shown(app) == "00:00.0"
        assert laps(app) == []
        await key(pilot, "space")
        clock.t += 1.3125
        await settle(pilot)
        assert shown(app) == "00:01.3"

    run(scenario)


def test_reset_ignored_while_running():
    async def scenario(app, pilot, clock):
        await key(pilot, "space")
        clock.t += 7.4375
        await key(pilot, "l")
        await key(pilot, "r")
        clock.t += 1.0
        await settle(pilot)
        assert shown(app) == "00:08.4"
        assert len(laps(app)) == 1

    run(scenario)


def test_intent_lap_shows_own_duration():
    async def scenario(app, pilot, clock):
        await key(pilot, "space")
        clock.t += 5.3125
        await key(pilot, "l")
        clock.t += 7.125   # second lap: 00:07.1, total 00:12.4
        await key(pilot, "l")
        clock.t += 61.8125  # third lap: 01:01.8, total 01:14.2
        await key(pilot, "l")
        rows = laps(app)
        assert len(rows) == 3
        joined = "\n".join(rows)
        for lap in ("00:05.3", "00:07.1", "01:01.8"):
            assert lap in joined, joined

    run(scenario)


def test_intent_newest_lap_first():
    async def scenario(app, pilot, clock):
        await key(pilot, "space")
        for step in (1.0625, 2.0625, 3.0625):
            clock.t += step
            await key(pilot, "l")
        rows = laps(app)
        assert len(rows) == 3
        # lap 1 reads 00:01.0 whether laps show splits or totals
        assert "00:01.0" in rows[-1] and "00:01.0" not in rows[0], rows

    run(scenario)


def test_intent_hours_format():
    async def scenario(app, pilot, clock):
        await key(pilot, "space")
        clock.t += 3723.4375
        await settle(pilot)
        assert "1:02:03.4" in text_of(app.query_one("#elapsed"))

    run(scenario)
