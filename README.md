# weld-ml-v2

This repository contains Bayesian optimization notebooks for weld experiments.

## Windows Setup for BoTorch Fused qLogEHVI Kernel

When running Ax/BoTorch on Windows in Jupyter, you may see a warning like:

```text
UserWarning: Failed to compile fused qLogEHVI C++ extension: Command '['where', 'cl']' returned non-zero exit status 1.
Falling back to the pure-Python implementation. To get ~3x speedup, ensure a C++ compiler and the `ninja` package are installed.
```

This means `cl.exe` (MSVC compiler) is not visible inside the notebook kernel process.

### 1) Install Visual Studio C++ Build Tools

Install **Visual Studio 2022 Build Tools** with C++ tooling:

1. Install "Desktop development with C++".
2. Ensure MSVC toolchain is included.

Expected default path:

```text
C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools
```

### 2) Install `ninja` in the same Python environment

Install into the environment used by your notebook kernel:

```powershell
pip install ninja
```

### 3) Important notebook note

VS Code terminal/workspace environment settings alone are often **not enough** for Jupyter kernels. The kernel can still start without MSVC variables, even if your terminal has them.

### 4) Add VS Code workspace setting (.vscode/settings.json)

Add this in `.vscode/settings.json` so VS Code terminals start with MSVC loaded:

```json
{
	"terminal.integrated.profiles.windows": {
		"Command Prompt (MSVC)": {
			"path": "cmd.exe",
			"args": [
				"/k",
				"C:\\Program Files (x86)\\Microsoft Visual Studio\\2022\\BuildTools\\VC\\Auxiliary\\Build\\vcvars64.bat"
			]
		}
	},
	"terminal.integrated.defaultProfile.windows": "Command Prompt (MSVC)"
}
```

This is useful for terminal-based runs (for example pure Python scripts). For Jupyter notebooks, keep the preload cell below because the kernel process may not inherit terminal profile environment variables.

### 5) Add a preload cell as the first code cell in the notebook

Run this before importing Ax/BoTorch. It loads `vcvars64.bat` into `os.environ` inside the kernel process.

```python
# Bootstrap MSVC toolchain inside the kernel process so BoTorch can build fused kernels on Windows.
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import shutil


def _load_msvc_env_from_vcvars() -> bool:
	vcvars = Path(
		r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
	)
	if not vcvars.exists():
		print(f"MSVC bootstrap skipped: {vcvars} not found.")
		return False

	dump_env_cmd = Path(tempfile.gettempdir()) / "_dump_msvc_env.cmd"
	dump_env_cmd.write_text(
		"@echo off\n"
		f"call \"{vcvars}\" >nul\n"
		"if errorlevel 1 exit /b 1\n"
		"set\n",
		encoding="utf-8",
	)

	try:
		proc = subprocess.run(
			["cmd.exe", "/d", "/c", str(dump_env_cmd)],
			capture_output=True,
			text=True,
			encoding="mbcs",
			errors="replace",
			check=True,
		)
	except subprocess.CalledProcessError as exc:
		print(f"MSVC bootstrap failed with return code {exc.returncode}.")
		if exc.stderr:
			print(exc.stderr.strip())
		return False

	for line in proc.stdout.splitlines():
		if "=" in line:
			key, value = line.split("=", 1)
			os.environ[key] = value

	# Keep active venv Scripts folder on PATH.
	scripts_dir = str(Path(sys.executable).resolve().parent)
	path_parts = os.environ.get("PATH", "").split(os.pathsep)
	if scripts_dir not in path_parts:
		os.environ["PATH"] = scripts_dir + os.pathsep + os.environ.get("PATH", "")

	return True


loaded = _load_msvc_env_from_vcvars()
print("MSVC env loaded:", loaded)
print("cl:", shutil.which("cl"))
print("ninja:", shutil.which("ninja"))
```

### 6) Verify

In that first cell output, confirm:

1. `MSVC env loaded: True`
2. `cl:` points to `cl.exe`
3. `ninja:` points to `ninja.exe`

If these are set, BoTorch should compile/use the fused kernel path instead of falling back to pure Python.

