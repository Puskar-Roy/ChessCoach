# PyInstaller recipe for the coach backend (bridge.py): a folder with chesscoach-backend.exe and everything it needs.
#   python -m PyInstaller packaging/backend.spec --noconfirm --distpath build/dist --workpath build/work
# The release script (tools/build_release.py) runs this for you.
import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

stockfish = os.environ.get("CHESSCOACH_STOCKFISH")
if not stockfish or not Path(stockfish).is_file():
    candidates = sorted((ROOT / "bin").rglob("stockfish*.exe"))
    stockfish = str(candidates[0]) if candidates else None
if not stockfish:
    raise SystemExit("Stockfish not found: put it under bin/ or set CHESSCOACH_STOCKFISH to stockfish.exe")

datas = [
    (str(ROOT / "data" / "openings.json"), "data"),     # the opening book
    (stockfish, "bin"),                                  # engine.find_stockfish() looks in <bundle>/bin
]
model = ROOT / "models" / "pieces.npz"                   # the piece recogniser: optional (see models/README.md)
if os.environ.get("CHESSCOACH_NO_MODEL") == "1":
    print("NOTE: CHESSCOACH_NO_MODEL=1 - building WITHOUT the piece recogniser, even if models/pieces.npz exists.")
elif model.is_file():
    datas.append((str(model), "models"))
else:
    print("NOTE: models/pieces.npz not found - building WITHOUT the piece recogniser (joining a game in progress will not be available).")
stockfish_licence = Path(stockfish).parent / "Copying.txt"
if stockfish_licence.is_file():
    datas.append((str(stockfish_licence), "bin"))

a = Analysis(
    [str(ROOT / "bridge.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["comtypes.client", "pyttsx3.drivers", "pyttsx3.drivers.sapi5"],
    excludes=["tkinter", "PIL", "pytest", "matplotlib", "scipy", "pandas", "IPython", "numpy.tests", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="chesscoach-backend",
    console=True,          # stdin/stdout carry the protocol; the app starts it with its window hidden
    upx=False,
    icon=str(ROOT / "app" / "build" / "icon.ico") if (ROOT / "app" / "build" / "icon.ico").is_file() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="backend")
