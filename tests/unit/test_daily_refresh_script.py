"""The daily refresh script must not call a partial drug crawl a failure.

A partial crawl (exit code 2) is loaded and reported in ATTENTION.md; the withdrawal safeguard
holds.
Only a step that really failed (nothing loaded) turns the run red.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")

# a stand-in for `uv run --no-sync python -X utf8 -m pharmavique.bootstrap.cli <command> ...`
FAKE_UV = """#!/usr/bin/env bash
echo "$@"
command="$8"
case "$command" in
  sfda-update) exit "${FAKE_UPDATE_CODE:-0}" ;;
  cache-invalidate|notify-emails) exit 4 ;;
  sfda-withdraw-absent) exit 2 ;;
  *) exit "${FAKE_OTHER_CODE:-0}" ;;
esac
"""


def run_script(
    tmp_path: Path, update_code: int, other_code: int = 0, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts" / "daily_refresh.sh"
    script.write_bytes((ROOT / "scripts" / "daily_refresh.sh").read_bytes().replace(b"\r\n", b"\n"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV, encoding="utf-8", newline="\n")
    uv.chmod(uv.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "STEPS": "drugs",
        "FAKE_UPDATE_CODE": str(update_code),
        "FAKE_OTHER_CODE": str(other_code),
        **(extra_env or {}),
    }
    assert BASH is not None
    return subprocess.run(  # noqa: S603
        [BASH, "scripts/daily_refresh.sh"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_a_partial_drug_crawl_is_loaded_and_is_not_a_failure(tmp_path: Path) -> None:
    result = run_script(tmp_path, update_code=2)
    assert "| drugs-load | exit 0 |" in result.stdout
    assert result.returncode == 0, result.stdout


def test_a_complete_drug_crawl_succeeds(tmp_path: Path) -> None:
    assert run_script(tmp_path, update_code=0).returncode == 0


def test_a_drug_crawl_that_loaded_nothing_is_a_failure(tmp_path: Path) -> None:
    result = run_script(tmp_path, update_code=1)
    assert "drugs-load" not in result.stdout
    assert result.returncode == 1


def test_a_step_after_the_crawl_that_fails_is_a_failure(tmp_path: Path) -> None:
    assert run_script(tmp_path, update_code=0, other_code=1).returncode == 1


def events(tmp_path: Path) -> list[dict[str, object]]:
    (day,) = (tmp_path / "data" / "refresh").glob("20*")
    lines = (day / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_every_step_writes_one_json_event(tmp_path: Path) -> None:
    run_script(tmp_path, update_code=2)

    steps = [e for e in events(tmp_path) if e["event"] == "step"]
    assert [e["step"] for e in steps][:2] == ["drugs-update", "drugs-load"]
    update = steps[0]
    assert update["exit_code"] == 2
    assert update["failed"] is False  # a partial crawl is not a failure
    assert isinstance(update["minutes"], int)
    assert str(update["time"]).endswith("Z")


def test_a_failed_step_is_marked_failed_in_the_events_and_the_run_line_counts_it(
    tmp_path: Path,
) -> None:
    run_script(tmp_path, update_code=0, other_code=1)

    found = events(tmp_path)
    failed = [e for e in found if e["event"] == "step" and e["failed"] is True]
    assert failed
    run = found[-1]
    assert run["event"] == "run"
    assert run["failed_steps"] == len(failed)  # the run line agrees with the steps
    assert run["steps"] == "drugs"


def test_the_events_never_hold_log_text(tmp_path: Path) -> None:
    run_script(tmp_path, update_code=0)

    for event in events(tmp_path):
        assert set(event) <= {
            "event",
            "time",
            "step",
            "exit_code",
            "minutes",
            "failed",
            "failed_steps",
            "steps",
        }


def loaded_before(tmp_path: Path, run_id: str = "update-20261101") -> None:
    sfda = tmp_path / "data" / "sfda"
    (sfda / run_id).mkdir(parents=True)
    (sfda / run_id / "records.jsonl").write_text("{}" + chr(10), encoding="utf-8")
    (sfda / "loaded.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")


def load_log(tmp_path: Path) -> str:
    (day,) = (tmp_path / "data" / "refresh").glob("20*")
    return (day / "drugs-load.log").read_text(encoding="utf-8")


def test_the_load_takes_only_what_changed_since_the_run_last_loaded(tmp_path: Path) -> None:
    loaded_before(tmp_path)

    run_script(tmp_path, update_code=0, extra_env={"FULL_LOAD": "1"})

    assert "--changed-since update-20261101" in load_log(tmp_path)


def test_fridays_load_everything(tmp_path: Path) -> None:
    loaded_before(tmp_path)

    run_script(tmp_path, update_code=0, extra_env={"FULL_LOAD": "5"})

    assert "--changed-since" not in load_log(tmp_path)


def test_without_a_loaded_run_on_this_machine_everything_is_loaded(tmp_path: Path) -> None:
    run_script(tmp_path, update_code=0, extra_env={"FULL_LOAD": "1"})

    assert "--changed-since" not in load_log(tmp_path)


def test_a_successful_load_remembers_its_run(tmp_path: Path) -> None:
    loaded_before(tmp_path)

    run_script(tmp_path, update_code=0, extra_env={"FULL_LOAD": "1"})

    loaded = json.loads((tmp_path / "data" / "sfda" / "loaded.json").read_text(encoding="utf-8"))
    assert loaded["run_id"].startswith("update-20")
    assert loaded["run_id"] != "update-20261101"


def test_a_failed_load_keeps_the_earlier_run(tmp_path: Path) -> None:
    loaded_before(tmp_path)

    run_script(tmp_path, update_code=0, other_code=1, extra_env={"FULL_LOAD": "1"})

    loaded = json.loads((tmp_path / "data" / "sfda" / "loaded.json").read_text(encoding="utf-8"))
    assert loaded["run_id"] == "update-20261101"
