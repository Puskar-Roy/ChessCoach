"""Build the Windows release: an installer and a single-file portable .exe, from a clean checkout.

    python tools/build_release.py            # backend + installer + portable, then a self-test of the result
    python tools/build_release.py --dir      # only the unpacked app folder (fast, for trying a build)

What goes in (all of it inside the app, nothing to install for the user):
  * the Electron desktop app (app/)
  * the coach backend frozen with PyInstaller (bridge.py + the vision/trainer code, opening book, piece model)
  * Stockfish (bin/stockfish*.exe, or CHESSCOACH_STOCKFISH)
Requirements on the build machine: the project's .venv with requirements-build.txt and Node 22.12+
(or a Node that can run electron-builder). The piece model models/pieces.npz is optional.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
BUILD = ROOT / "build"
RELEASE = ROOT / "release"


def run(command, **kwargs):
    print("\n>", " ".join(str(c) for c in command), flush=True)
    subprocess.run([str(c) for c in command], check=True, **kwargs)


def npm():
    return shutil.which("npm.cmd") or shutil.which("npm") or "npm"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", action="store_true", help="build only release/win-unpacked (no installer, no portable exe)")
    parser.add_argument("--skip-backend", action="store_true", help="reuse build/dist/backend from an earlier run")
    parser.add_argument("--no-selftest", action="store_true")
    parser.add_argument("--no-model", action="store_true",
                        help="leave the piece recogniser out even if models/pieces.npz exists (use this for builds you share)")
    args = parser.parse_args()

    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        python = Path(sys.executable)
    if args.no_model or not (ROOT / "models" / "pieces.npz").is_file():
        print("NOTE: this build will not contain the piece recogniser (models/pieces.npz):")
        print("      joining a game that is already under way will not be available (see models/README.md). Continuing.")

    if args.no_model:
        os.environ["CHESSCOACH_NO_MODEL"] = "1"  # read by packaging/backend.spec

    # 1. icon
    if not (APP / "build" / "icon.ico").is_file():
        run([python, ROOT / "tools" / "make_icon.py"])

    # 2. the coach backend
    if not args.skip_backend:
        shutil.rmtree(BUILD, ignore_errors=True)
        run([python, "-m", "PyInstaller", ROOT / "packaging" / "backend.spec", "--noconfirm",
             "--distpath", BUILD / "dist", "--workpath", BUILD / "work"], cwd=ROOT)
    backend = BUILD / "dist" / "backend" / "chesscoach-backend.exe"
    if not backend.is_file():
        print("The backend was not built:", backend)
        return 1

    # 3. the desktop app
    if not (APP / "node_modules" / ".bin" / "electron-builder.cmd").is_file():
        run([npm(), "--prefix", APP, "ci"])
    shutil.rmtree(RELEASE, ignore_errors=True)
    env = {**os.environ, "CSC_IDENTITY_AUTO_DISCOVERY": "false"}  # no code-signing certificate: skip the search
    run([npm(), "--prefix", APP, "run", "pack" if args.dir else "dist"], env=env)

    # 4. prove the result works: start the packaged app in self-test mode
    unpacked = RELEASE / "win-unpacked" / "ChessCoach.exe"
    if not args.no_selftest:
        profile = tempfile.mkdtemp(prefix="chesscoach-selftest-")
        result = subprocess.run([str(unpacked), "--self-test"], capture_output=True, text=True, timeout=180,
                                env={**os.environ, "CHESSCOACH_TEST": "1", "CHESSCOACH_PROFILE": profile})
        shutil.rmtree(profile, ignore_errors=True)
        print("\nSelf-test of the packaged app:\n" + result.stdout)
        if result.returncode != 0:
            print(result.stderr)
            print("SELF-TEST FAILED")
            return 1

    # 5. report
    print("\nBuilt:")
    for artifact in sorted(RELEASE.glob("*.exe")):
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        print(f"  {artifact.name}  {artifact.stat().st_size / 1e6:.0f} MB  sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
