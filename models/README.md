# Piece recognizer

`pieces.npz` contains the NumPy weights for the classifier used when joining a board in progress.
It is not needed to follow ordinary moves from a known starting position. Without the model,
ChessCoach cannot automatically reconstruct a new position after the live board drifts out of sync;
restart the session or re-enter the position instead.

The current weights were trained on a mixture of website piece sets and synthetic glyphs. An exact
source and license manifest for those inputs is not recorded here. Before publishing the current
weights, verify and document their provenance, or retrain with inputs cleared for public release.

From an activated development environment (`pip install -r requirements-training.txt`):

```powershell
python tools/train_pieces.py PATH_TO_PIECE_SETS --hold held_out_ --out models/pieces.npz
python tools/benchmark_midgame.py PATH_TO_PIECE_SETS --only held_out_ --model models/pieces.npz
```

Supply one directory per set, with twelve files named like `wP.svg` through `bK.svg` or `wp.png`
through `bk.png`. The `--hold` prefix keeps matching sets out of training; replace `held_out_` with
the prefix of your held-out folders. Record the input sources, licenses, training command, and
held-out results when replacing the weights.
