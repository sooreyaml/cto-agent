from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_entrypoint_retries_migrations_before_starting_uvicorn(tmp_path: Path) -> None:
    state = tmp_path / "migration-attempts"
    started = tmp_path / "uvicorn-started"
    _write_executable(
        tmp_path / "alembic",
        "#!/bin/sh\n"
        f"count=0; [ -f '{state}' ] && count=$(cat '{state}'); count=$((count + 1)); "
        f"echo $count > '{state}'; [ $count -ge 2 ]\n",
    )
    _write_executable(
        tmp_path / "uvicorn",
        f"#!/bin/sh\ntouch '{started}'\n",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path}:{env['PATH']}",
            "MIGRATION_MAX_ATTEMPTS": "3",
            "MIGRATION_RETRY_SECONDS": "0",
        }
    )

    result = subprocess.run(
        ["/bin/sh", str(ROOT / "docker-entrypoint.sh")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert state.read_text(encoding="utf-8").strip() == "2"
    assert started.exists()
    assert "attempt 1/3" in result.stdout
    assert "attempt 2/3" in result.stdout


def test_entrypoint_does_not_start_uvicorn_after_migration_failure(tmp_path: Path) -> None:
    started = tmp_path / "uvicorn-started"
    _write_executable(tmp_path / "alembic", "#!/bin/sh\nexit 1\n")
    _write_executable(tmp_path / "uvicorn", f"#!/bin/sh\ntouch '{started}'\n")
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path}:{env['PATH']}",
            "MIGRATION_MAX_ATTEMPTS": "2",
            "MIGRATION_RETRY_SECONDS": "0",
        }
    )

    result = subprocess.run(
        ["/bin/sh", str(ROOT / "docker-entrypoint.sh")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert not started.exists()
    assert "failed after 2 attempts" in result.stderr
