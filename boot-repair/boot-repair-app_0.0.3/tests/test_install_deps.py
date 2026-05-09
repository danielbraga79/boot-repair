from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestInstallDeps(unittest.TestCase):
    @property
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def make_stub_module(self, root: Path, module_name: str) -> None:
        module_path = root / module_name
        module_path.mkdir(parents=True, exist_ok=True)
        (module_path / "__init__.py").write_text("__version__ = '0.1'\n", encoding="utf-8")

    def make_python_package(self, dist_root: Path, package_name: str) -> None:
        package_dir = dist_root / f"{package_name}-src"
        package_src = package_dir / package_name
        package_src.mkdir(parents=True, exist_ok=True)
        (package_src / "__init__.py").write_text("__version__ = '0.1'\n", encoding="utf-8")
        (package_dir / "setup.py").write_text(
            "from setuptools import setup, find_packages\n\n"
            f"setup(name=\"{package_name}\", version=\"0.1\", packages=find_packages())\n",
            encoding="utf-8",
        )
        dist_dir = dist_root / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [sys.executable, "setup.py", "sdist", "--dist-dir", str(dist_dir)],
            cwd=str(package_dir),
            check=True,
            capture_output=True,
            text=True,
        )

    def make_stub_bin(self, root: Path, script_name: str, content: str) -> Path:
        path = root / script_name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
        return path

    def make_stub_pacman(self, root: Path, installed: str, available: str, module_root: Path) -> None:
        content = f"""#!/bin/bash
cmd="$1"; shift
case "$cmd" in
  -Q)
    pkg="$1"
    if [[ " {installed} " =~ " $pkg " ]]; then
      exit 0
    fi
    exit 1
    ;;
  -Si)
    pkg="$1"
    if [[ " {available} " =~ " $pkg " ]]; then
      exit 0
    fi
    exit 1
    ;;
  -S)
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --noconfirm|--needed)
          shift
          ;;
        *)
          pkg="$1"
          case "$pkg" in
            python-customtkinter|python-darkdetect|python-pyudev)
              mkdir -p "{module_root}/${{pkg#python-}}"
              mkdir -p "{module_root}/${{pkg#python3-}}"
              cat > "{module_root}/${{pkg#python-}}/__init__.py" <<'EOF'
__version__ = '0.1'
EOF
              ;;
            *)
              ;;
          esac
          shift
          ;;
      esac
    done
    exit 0
    ;;
  *)
    echo "Unsupported pacman command: $cmd" >&2
    exit 1
    ;;
esac
"""
        self.make_stub_bin(root, "pacman", content)

    def make_stub_apt(self, root: Path, installed: str, available: str, module_root: Path) -> None:
        content = f"""#!/bin/bash
cmd="$1"; shift
case "$cmd" in
  cache)
    if [[ "$1" == "show" ]]; then
      pkg="$2"
      if [[ " {available} " =~ " $pkg " ]]; then
        exit 0
      fi
      exit 1
    fi
    ;;
  update)
    exit 0
    ;;
  install)
    while [[ $# -gt 0 ]]; do
      case "$1" in
        -y)
          shift
          ;;
        *)
          pkg="$1"
          case "$pkg" in
            python3-customtkinter|python3-darkdetect|python3-pyudev)
              mkdir -p "{module_root}/$pkg"
              mkdir -p "{module_root}/${{pkg#python3-}}"
              cat > "{module_root}/${{pkg#python3-}}/__init__.py" <<'EOF'
__version__ = '0.1'
EOF
              ;;
            *)
              ;;
          esac
          shift
          ;;
      esac
    done
    exit 0
    ;;
  *)
    echo "Unsupported apt command: $cmd" >&2
    exit 1
    ;;
esac
"""
        self.make_stub_bin(root, "apt", content)
        self.make_stub_bin(root, "apt-cache", "#!/bin/bash\nexec apt-cache \"$@\"\n")

    def make_stub_dpkg_query(self, root: Path, installed: str) -> None:
        content = f"""#!/bin/bash
pkg="$1"
if [[ " {installed} " =~ " $pkg " ]]; then
  printf 'install ok installed'
  exit 0
fi
exit 1
"""
        self.make_stub_bin(root, "dpkg-query", content)

    def make_sudo_stub(self, root: Path) -> None:
        content = "#!/bin/bash\nexec \"$@\"\n"
        self.make_stub_bin(root, "sudo", content)

    def run_script(self, script_path: Path, cwd: Path, env: dict, args: list[str]) -> subprocess.CompletedProcess[str]:
        command = ["bash", str(script_path), *args]
        return subprocess.run(command, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=90)

    def make_test_env(self, stubbin: Path, module_root: Path, dist_root: Path | None = None) -> dict:
        env = os.environ.copy()
        env["PATH"] = f"{stubbin}:{env['PATH']}"
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONPATH"] = str(module_root)
        env["PIP_NO_CACHE_DIR"] = "1"
        if dist_root is not None:
            env["PIP_FIND_LINKS"] = str(dist_root / "dist")
        return env

    def test_launcher_uses_venv_python_when_venv_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stub = temp_path / "stub"
            stub.mkdir()
            script_link = temp_path / "boot-repair.sh"
            script_link.symlink_to(self.repo_root / "boot-repair.sh")
            venv_dir = temp_path / ".venv"
            (venv_dir / "bin").mkdir(parents=True)
            python_exec = venv_dir / "bin" / "python"
            python_exec.write_text("#!/bin/bash\necho venv-python\n", encoding="utf-8")
            python_exec.chmod(0o755)

            result = subprocess.run(
                ["bash", "-c", f"cd {temp_path} && source ./boot-repair.sh 2>/dev/null && resolve_python_interpreter"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(python_exec), result.stdout.strip())

    def test_install_deps_arch_no_native_packages_creates_venv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            script_link = temp_path / "install-deps.sh"
            script_link.symlink_to(self.repo_root / "install-deps.sh")

            stubbin = temp_path / "stubbin"
            stubbin.mkdir()
            module_root = temp_path / "stub_modules"
            module_root.mkdir()
            self.make_stub_module(module_root, "pyudev")

            self.make_stub_pacman(
                stubbin,
                installed="python3 tk util-linux efibootmgr dosfstools python-pyudev",
                available="",
                module_root=module_root,
            )
            self.make_sudo_stub(stubbin)

            dist_root = temp_path / "package_index"
            dist_root.mkdir()
            self.make_python_package(dist_root, "customtkinter")
            self.make_python_package(dist_root, "darkdetect")

            env = self.make_test_env(stubbin, module_root, dist_root)

            result = self.run_script(script_link, temp_path, env, ["arch"])
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((temp_path / ".venv" / "bin" / "python").exists())

            venv_python = temp_path / ".venv" / "bin" / "python"
            verify = subprocess.run(
                [str(venv_python), "-c", "import customtkinter, darkdetect, tkinter, pyudev"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(verify.returncode, 0, verify.stderr)

    def test_install_deps_arch_native_packages_installed_no_venv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            script_link = temp_path / "install-deps.sh"
            script_link.symlink_to(self.repo_root / "install-deps.sh")

            stubbin = temp_path / "stubbin"
            stubbin.mkdir()
            module_root = temp_path / "stub_modules"
            module_root.mkdir()
            self.make_stub_module(module_root, "tkinter")
            self.make_stub_module(module_root, "pyudev")

            # native packages are available but not preinstalled
            self.make_stub_pacman(
                stubbin,
                installed="python3 tk util-linux efibootmgr dosfstools python-pyudev",
                available="python-customtkinter python-darkdetect",
                module_root=module_root,
            )
            self.make_sudo_stub(stubbin)

            env = self.make_test_env(stubbin, module_root)

            result = self.run_script(script_link, temp_path, env, ["arch"])
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse((temp_path / ".venv").exists())
            self.assertIn("Installing native package", result.stdout)
            self.assertIn("All Python dependencies are available", result.stdout)

    def test_install_deps_reuses_existing_venv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            script_link = temp_path / "install-deps.sh"
            script_link.symlink_to(self.repo_root / "install-deps.sh")

            stubbin = temp_path / "stubbin"
            stubbin.mkdir()
            module_root = temp_path / "stub_modules"
            module_root.mkdir()
            self.make_stub_module(module_root, "pyudev")

            self.make_stub_pacman(
                stubbin,
                installed="python3 tk util-linux efibootmgr dosfstools python-pyudev",
                available="",
                module_root=module_root,
            )
            self.make_sudo_stub(stubbin)

            dist_root = temp_path / "package_index"
            dist_root.mkdir()
            self.make_python_package(dist_root, "customtkinter")
            self.make_python_package(dist_root, "darkdetect")

            env = self.make_test_env(stubbin, module_root, dist_root)

            first = self.run_script(script_link, temp_path, env, ["arch"])
            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            self.assertTrue((temp_path / ".venv").exists())

            second = self.run_script(script_link, temp_path, env, ["arch"])
            self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
            self.assertIn("Reusing existing Python virtual environment", second.stdout)


if __name__ == '__main__':
    raise SystemExit(unittest.main())
