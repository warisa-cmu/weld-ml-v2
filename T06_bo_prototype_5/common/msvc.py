"""Load the MSVC compiler environment so BoTorch can build its fast kernels on Windows.

Ported from T06_bo_prototype_4/main.ipynb. A VS Code terminal with the
"Command Prompt (MSVC)" profile already has the compiler; a Jupyter kernel, and
any script it starts, does not. `ensure()` is called by common/ax_client.py
before Ax runs, so both cases end up with the compiler. Without it Ax still
works, only slower.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import settings

_loaded: bool | None = None


def ensure(verbose: bool = False) -> bool:
    """Make sure `cl` is on PATH, loading settings.VCVARS once if needed.

    Returns True if the compiler is available. Never raises: on any problem it
    prints why (when verbose) and returns False.
    """
    global _loaded
    if shutil.which("cl"):
        return True
    if _loaded is not None:
        return _loaded
    _loaded = _load(settings.VCVARS, verbose)
    return _loaded


def _load(vcvars: Path | None, verbose: bool) -> bool:
    if sys.platform != "win32" or vcvars is None:
        return False
    vcvars = Path(vcvars)
    if not vcvars.exists():
        if verbose:
            print(f"MSVC not loaded: {vcvars} not found (settings.VCVARS).")
        return False

    dump = Path(tempfile.gettempdir()) / "_dump_msvc_env.cmd"
    dump.write_text(
        f'@echo off\ncall "{vcvars}" >nul\nif errorlevel 1 exit /b 1\nset\n',
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(
            ["cmd.exe", "/d", "/c", str(dump)],
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        if verbose:
            print(f"MSVC not loaded: {exc}")
        return False

    for line in proc.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            os.environ[key] = value

    # Keep the active virtual environment's Scripts folder (ninja) on PATH.
    scripts = str(Path(sys.executable).resolve().parent)
    if scripts not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = scripts + os.pathsep + os.environ.get("PATH", "")

    ok = shutil.which("cl") is not None
    if verbose:
        print("MSVC loaded." if ok else "MSVC loaded, but cl is still not on PATH.")
    return ok
