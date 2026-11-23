"""The daily refresh script must not call a partial drug crawl a failure.

A partial crawl (exit code 2) is loaded and reported in ATTENTION.md; the withdrawal safeguard
holds.
Only a step that really failed (nothing loaded) turns the run red.
"""

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
command="$8"
case "$command" in
  sfda-update) exit "${FAKE_UPDATE_CODE:-0}" ;;
  cache-invalidate|notify-emails) exit 4 ;;
  sfda-withdraw-absent) exit 2 ;;
  *) exit "${FAKE_OTHER_CODE:-0}" ;;
esac
"""


def run_script(
    tmp_path: Path, update_code: int, other_code: int = 0
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
