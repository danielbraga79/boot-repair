from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class TestLauncher(unittest.TestCase):
    def test_launcher_points_to_main_app(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        launcher = repo_root / 'boot-repair.sh'
        self.assertTrue(launcher.exists(), f'Launcher script not found: {launcher}')

        contents = launcher.read_text(encoding='utf-8')
        self.assertIn('MAIN_APP="${SCRIPT_DIR}/boot-repair-app_0.0.3/main.py"', contents)
        self.assertIn('exec "${python_exec}" "${MAIN_APP}" "$@"', contents)

    def test_launcher_is_executable(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        launcher = repo_root / 'boot-repair.sh'
        self.assertTrue(launcher.stat().st_mode & 0o111, 'Launcher script is not executable')

    def test_launcher_syntax_is_valid(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        launcher = repo_root / 'boot-repair.sh'
        result = subprocess.run(['bash', '-n', str(launcher)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f'Launcher syntax invalid: {result.stderr}')

    def test_main_app_compiles(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        main_app = repo_root / 'boot-repair-app_0.0.3' / 'main.py'
        result = subprocess.run([sys.executable, '-m', 'py_compile', str(main_app)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f'Main app does not compile: {result.stderr}')


if __name__ == '__main__':
    raise SystemExit(unittest.main())
