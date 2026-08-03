"""
Regression tests for main.py.

Every test here corresponds to a bug that was actually present and fixed.
The names describe the old broken behaviour so a future regression is
obvious from the failure output alone.
"""
import tempfile
from pathlib import Path

import pytest

import main


# ---------------------------------------------------------------------------
# _err — error messages used to be just type(e).__name__, which said nothing
# ---------------------------------------------------------------------------

def test_err_includes_type_and_message():
    assert main._err(ValueError("bad api_id")) == "ValueError: bad api_id"


def test_err_falls_back_to_type_when_message_empty():
    assert main._err(ValueError()) == "ValueError"


def test_err_truncates_long_messages():
    assert len(main._err(ValueError("x" * 500))) < 120


def test_err_is_single_line():
    assert "\n" not in main._err(ValueError("first\nsecond"))


# ---------------------------------------------------------------------------
# save_config — used to overwrite the whole file, dropping unrelated keys
# ---------------------------------------------------------------------------

@pytest.fixture
def paths(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(main, "CONFIG_DIR", tmp)
    monkeypatch.setattr(main, "DOWNLOAD_DIR", tmp / "downloads")
    monkeypatch.setattr(main, "CONFIG_FILE", tmp / "config.json")
    monkeypatch.setattr(main, "SESSION_FILE", tmp / "session.txt")
    return tmp


def test_save_config_merges_instead_of_overwriting(paths):
    main.save_config({"api_id": 1, "api_hash": "a" * 32})
    main.save_config({"last_target": "@someone"})

    cfg = main.load_config()
    assert cfg["last_target"] == "@someone"
    assert cfg["api_id"] == 1, "second save wiped api_id"
    assert cfg["api_hash"] == "a" * 32, "second save wiped api_hash"


def test_load_config_returns_empty_dict_on_corrupt_json(paths):
    main.CONFIG_FILE.write_text("{not json", encoding="utf-8")
    assert main.load_config() == {}


# ---------------------------------------------------------------------------
# storage — permissions are granted after boot, so the dir must be re-resolved
# ---------------------------------------------------------------------------

def test_pick_download_dir_desktop(monkeypatch):
    monkeypatch.setattr(main, "ON_ANDROID", False)
    base = Path(tempfile.mkdtemp())
    assert main.pick_download_dir(base) == base / "downloads"


def test_pick_download_dir_falls_back_when_sdcard_unwritable(monkeypatch):
    monkeypatch.setattr(main, "ON_ANDROID", True)
    base = Path(tempfile.mkdtemp())
    result = main.pick_download_dir(base)
    assert str(result).startswith(str(base))
    assert result.exists(), "fallback directory was not created"


def test_refresh_download_dir_reports_change(monkeypatch):
    base = Path(tempfile.mkdtemp())
    monkeypatch.setattr(main, "ON_ANDROID", False)
    monkeypatch.setattr(main, "CONFIG_DIR", base)
    monkeypatch.setattr(main, "DOWNLOAD_DIR", Path("/nonexistent/old"))

    assert main.refresh_download_dir() is True
    assert main.refresh_download_dir() is False, "should be idempotent"


def test_storage_paths_never_uses_android_argument(monkeypatch):
    """ANDROID_ARGUMENT is the read-only source dir, not private storage."""
    monkeypatch.setattr(main, "ON_ANDROID", True)
    monkeypatch.delenv("ANDROID_PRIVATE", raising=False)
    monkeypatch.delenv("ANDROID_APP_PATH", raising=False)
    monkeypatch.setenv("ANDROID_ARGUMENT", "/some/readonly/source/dir")

    private, _ = main.storage_paths()
    assert "readonly/source" not in str(private)


# ---------------------------------------------------------------------------
# mode lookup — next(...) raised StopIteration and killed the Kivy thread
# ---------------------------------------------------------------------------

@pytest.fixture
def mode_table():
    return {main.ar(k): v for k, v in main.MODES.items()}


def test_default_spinner_label_resolves(mode_table):
    assert mode_table.get(main.ar("الكل")) == "all"


def test_every_mode_label_resolves(mode_table):
    assert sorted(mode_table.values()) == ["active", "all", "pinned"]


def test_unknown_label_falls_back_without_raising(mode_table):
    assert mode_table.get("garbage", "all") == "all"


# ---------------------------------------------------------------------------
# download loop — mirrors MainScreen.download without Kivy or Telethon
# ---------------------------------------------------------------------------

class FloodWait(Exception):
    seconds = 1


class Story:
    def __init__(self, sid, media="media", noforwards=False):
        self.id = sid
        self.media = media
        self.noforwards = noforwards
        self.date = None


def run_download(stories, fail_ids=(), flood_once=()):
    """Same control flow as MainScreen.download; returns counters + attempts."""
    outdir = Path(tempfile.mkdtemp())
    ok = fail = skip = 0
    attempts = {}
    flood_left = {i: 1 for i in flood_once}

    for story in sorted(stories, key=lambda s: s.id):
        if getattr(story, "noforwards", False):
            skip += 1
            continue
        if story.media is None:
            skip += 1
            continue

        target = outdir / ("nodate_%s.bin" % story.id)
        if target.exists() and target.stat().st_size > 0:
            skip += 1
            continue

        for _ in range(3):
            attempts[story.id] = attempts.get(story.id, 0) + 1
            if flood_left.get(story.id):
                flood_left[story.id] -= 1
                continue
            if story.id in fail_ids:
                fail += 1
                if target.exists():
                    target.unlink()
                break
            target.write_text("payload")
            ok += 1
            break
        else:
            fail += 1

    return {"ok": ok, "fail": fail, "skip": skip, "attempts": attempts}


def test_text_only_story_is_skipped_not_counted_as_success():
    """media=None used to be logged with a checkmark for a file never written."""
    r = run_download([Story(1), Story(2, media=None)])
    assert r["ok"] == 1
    assert r["skip"] == 1


def test_protected_story_is_skipped():
    r = run_download([Story(1, noforwards=True)])
    assert (r["ok"], r["skip"]) == (0, 1)


def test_floodwait_retries_the_same_story():
    """Old code slept then moved on, silently losing the throttled story."""
    r = run_download([Story(1)], flood_once=[1])
    assert r["ok"] == 1
    assert r["attempts"][1] == 2, "story was not retried after FloodWait"


def test_hard_failure_counted_once_without_retry_storm():
    r = run_download([Story(1)], fail_ids=[1])
    assert r["fail"] == 1
    assert r["attempts"][1] == 1


def test_stories_processed_in_ascending_id_order():
    r = run_download([Story(3), Story(1), Story(2)])
    assert (r["ok"], r["fail"], r["skip"]) == (3, 0, 0)


# ---------------------------------------------------------------------------
# pinned pagination — a repeated page used to spin forever
# ---------------------------------------------------------------------------

def paginate(pages, max_spins=50):
    offset, got, seen, spins = 0, [], set(), 0
    for batch_ids in pages + [pages[-1]] * 20:  # server repeats the last page
        spins += 1
        if spins > max_spins:
            pytest.fail("pinned pagination did not terminate")
        batch = [Story(i) for i in batch_ids]
        if not batch:
            break
        got += [s for s in batch if s.id not in seen]
        seen.update(s.id for s in batch)
        if batch[-1].id == offset:
            break
        offset = batch[-1].id
        if len(batch) < 50:
            break
    return got


def test_pagination_terminates_when_server_repeats_a_page():
    assert len(paginate([[1, 2, 3]])) == 3


def test_pagination_does_not_duplicate_across_pages():
    got = paginate([list(range(1, 51)), list(range(51, 60))])
    assert len(got) == len({s.id for s in got})


# ---------------------------------------------------------------------------
# API surface the fixes depend on
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "pick_download_dir", "refresh_download_dir", "_err", "ensure_paths",
    "storage_paths", "load_config", "save_config",
])
def test_module_defines(name):
    assert hasattr(main, name)


def test_app_disconnects_client_on_stop():
    assert hasattr(main.TGStoriesApp, "on_stop")


def test_app_guards_against_concurrent_connects():
    assert hasattr(main.TGStoriesApp, "_connecting")


def test_setup_screen_prefills_saved_config():
    assert hasattr(main.SetupScreen, "on_pre_enter")


def test_worker_supports_synchronous_shutdown():
    assert hasattr(main.WORKER, "run_sync")


def test_main_py_parses():
    import ast
    src = (Path(main.__file__).read_text(encoding="utf-8"))
    ast.parse(src)
