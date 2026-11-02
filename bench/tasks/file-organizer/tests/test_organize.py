import json
from pathlib import Path

import pytest

from lightness.bench.testkit import run_cli

FILES = {
    "photo.jpg": "img1",
    "Scan.PDF": "pdf1",
    "notes.txt": "txt1",
    "song.mp3": "mp3",
    "clip.mov": "mov",
    "backup.zip": "zip",
    "script.py": "print(1)",
    "weird.xyz": "???",
    "IMG_2.JPEG": "img2",
    "Screenshot 2024-05-01 at 10.00.png": "shot",
}


def snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    d = tmp_path / "Downloads"
    d.mkdir()
    for name, content in FILES.items():
        (d / name).write_text(content)
    (d / ".DS_Store").write_text("hidden")
    (d / "old_project").mkdir()
    (d / "old_project" / "readme.md").write_text("keep me")
    return d


def organize(folder: Path, *flags: str):
    r = run_cli("organize.py", str(folder), *flags)
    assert r.returncode == 0, r.stderr
    return r


def plan_json(folder: Path) -> list[dict]:
    return json.loads(organize(folder, "--json").stdout)


def test_dry_run_changes_nothing(downloads):
    before = snapshot(downloads)
    organize(downloads)
    plan_json(downloads)
    assert snapshot(downloads) == before


def test_apply_moves_every_visible_top_level_file_without_loss(downloads):
    organize(downloads, "--apply")
    after = snapshot(downloads)
    for name, content in FILES.items():
        assert name not in after, f"{name} still at top level"
    assert sorted(after.values()) == sorted([*FILES.values(), "hidden", "keep me"])


def test_same_type_goes_together_different_types_apart(downloads):
    organize(downloads, "--apply")
    where = {Path(rel).name: Path(rel).parent for rel in snapshot(downloads)}
    assert where["photo.jpg"] == where["IMG_2.JPEG"]
    assert where["photo.jpg"] != where["Scan.PDF"]
    assert where["song.mp3"] != where["clip.mov"]


def test_json_plan_matches_what_apply_does(downloads):
    plan = plan_json(downloads)
    assert {p["src"] for p in plan} == set(FILES)
    organize(downloads, "--apply")
    for p in plan:
        assert (downloads / p["dst"]).exists()


def test_never_overwrites_existing_destination(downloads):
    plan = {p["src"]: p["dst"] for p in plan_json(downloads)}
    dest_dir = downloads / Path(plan["photo.jpg"]).parent
    dest_dir.mkdir(exist_ok=True)
    (dest_dir / "photo.jpg").write_text("already here")
    organize(downloads, "--apply")
    contents = sorted(snapshot(downloads).values())
    assert "already here" in contents and "img1" in contents


def test_second_run_does_nothing(downloads):
    organize(downloads, "--apply")
    before = snapshot(downloads)
    assert plan_json(downloads) == []
    organize(downloads, "--apply")
    assert snapshot(downloads) == before


def test_leaves_hidden_files_and_subfolders(downloads):
    organize(downloads, "--apply")
    assert (downloads / ".DS_Store").read_text() == "hidden"
    assert (downloads / "old_project" / "readme.md").read_text() == "keep me"


def test_intent_category_folder_names(downloads):
    organize(downloads, "--apply")
    expected = {
        "photo.jpg": "Images", "IMG_2.JPEG": "Images", "Scan.PDF": "Documents", "notes.txt": "Documents",
        "song.mp3": "Audio", "clip.mov": "Video", "backup.zip": "Archives", "script.py": "Code",
        "weird.xyz": "Other",
    }
    for name, folder in expected.items():
        assert (downloads / folder / name).exists(), f"{name} not in {folder}/"


def test_intent_collision_suffix(downloads):
    (downloads / "Images").mkdir()
    (downloads / "Images" / "photo.jpg").write_text("already here")
    organize(downloads, "--apply")
    assert (downloads / "Images" / "photo (1).jpg").read_text() == "img1"


def test_intent_screenshots_separate(downloads):
    organize(downloads, "--apply")
    assert (downloads / "Screenshots" / "Screenshot 2024-05-01 at 10.00.png").exists()
    assert not (downloads / "Images" / "Screenshot 2024-05-01 at 10.00.png").exists()
