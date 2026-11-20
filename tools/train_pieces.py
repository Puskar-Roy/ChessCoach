"""Train the piece recogniser (models/pieces.npz) from piece sets drawn on randomly coloured squares.

    python tools/train_pieces.py SETS_DIR [--hold cc_] [--out models/pieces.npz]

SETS_DIR holds one folder per piece set with the twelve pictures wP.svg ... bK.svg (or wp.png ... bk.png).
`--hold PREFIX` keeps the sets whose folder starts with PREFIX out of the training and reports how well the
network recognises those unseen sets: that is the number that matters, because a website's own set is
never part of the training.
"""

import argparse
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import resvg_py

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from piece_classifier import KINDS, MODEL_PATH, cell_vector  # noqa: E402
import sitegen  # noqa: E402
from sitegen import HIGHLIGHTS, THEMES  # noqa: E402


def glyph_sets() -> dict[str, dict[str, np.ndarray]]:
    """The font-drawn piece styles of the test-site generator, as sprite sets (more variety for the network)."""
    sets = {}
    for style in sitegen.PIECE_STYLES:
        sets[f"glyph_{style}"] = {("w" if symbol.isupper() else "b") + symbol.lower(): sitegen._sprite(symbol, 150, style)[:, :, [2, 1, 0, 3]] for symbol in "PNBRQKpnbrqk"}
    return sets


def load_set(folder: Path) -> dict[str, np.ndarray]:
    """{'wp': RGBA float picture, ...} for one set."""
    sprites = {}
    for color in "wb":
        for kind in KINDS:
            svg, png = folder / f"{color}{kind.upper()}.svg", folder / f"{color}{kind}.png"
            if svg.exists():
                text = svg.read_text(encoding="utf-8")
                root = text[: text.index(">") + 1]
                fixed = re.sub(r'\s(width|height)="[^"]*"', "", root)
                if "viewBox" not in root:
                    w, h = re.search(r'width="([\d.]+)', root), re.search(r'height="([\d.]+)', root)
                    fixed = fixed.replace("<svg", f'<svg viewBox="0 0 {w.group(1)} {h.group(1)}"', 1)
                fixed = fixed.replace("<svg", '<svg width="150" height="150"', 1)
                text = fixed + text[len(root):]
                data = bytes(resvg_py.svg_to_bytes(svg_string=text, width=150, height=150))
                image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
            elif png.exists():
                image = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)
            else:
                continue
            if image.shape[2] == 3:
                image = np.dstack([image, np.full(image.shape[:2], 255, np.uint8)])
            sprites[color + kind] = cv2.resize(image, (150, 150), interpolation=cv2.INTER_AREA).astype(np.float32)
    return sprites


def random_square(rng: np.random.Generator) -> np.ndarray:
    name = list(THEMES)[rng.integers(len(THEMES))]
    light, dark = THEMES[name]
    base = np.array(light if rng.random() < 0.5 else dark, np.float32)
    if rng.random() < 0.3:
        base = rng.uniform(40, 245, 3).astype(np.float32)
    return (base + rng.normal(0, 4, 3)).clip(0, 255)[::-1]  # BGR


def render_cell(sprite: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    side = int(rng.integers(44, 120))
    canvas = np.zeros((side, side, 3), np.float32) + random_square(rng)
    if rng.random() < 0.35:
        tint = np.array(list(HIGHLIGHTS.values())[rng.integers(3)][::-1], np.float32)
        alpha = rng.uniform(0.3, 0.6)
        canvas = canvas * (1 - alpha) + tint * alpha
    base_tone = canvas[0, 0].copy()
    other = (255 - base_tone) * 0.55 + base_tone * 0.2  # coordinate labels use the other square colour
    canvas = canvas.clip(0, 255).astype(np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    label_scale = side / rng.uniform(95, 135)
    if rng.random() < 0.5:  # rank number, top-left corner
        cv2.putText(canvas, "12345678"[rng.integers(8)], (int(side * 0.04), int(side * 0.2)), font, label_scale, tuple(float(v) for v in other), 1, cv2.LINE_AA)
    if rng.random() < 0.5:  # file letter, bottom-right corner
        cv2.putText(canvas, "abcdefgh"[rng.integers(8)], (int(side * 0.8), int(side * 0.95)), font, label_scale, tuple(float(v) for v in other), 1, cv2.LINE_AA)
    canvas = canvas.astype(np.float32)
    if rng.random() < 0.06:  # the red glow behind a king in check
        yy, xx = np.mgrid[0:side, 0:side]
        glow = np.clip(1 - np.hypot(xx - side / 2, yy - side / 2) / (side * 0.75), 0, 1) ** 1.5 * rng.uniform(0.5, 0.9)
        canvas = canvas * (1 - glow[:, :, None]) + np.array((60, 60, 235), np.float32) * glow[:, :, None]
    scale = rng.uniform(0.82, 1.02)
    size = min(side, int(side * scale))
    resized = cv2.resize(sprite, (size, size), interpolation=cv2.INTER_AREA if size < 150 else cv2.INTER_CUBIC)
    x = (side - size) // 2 + int(rng.integers(-side // 25, side // 25 + 1))
    y = (side - size) // 2 + int(rng.integers(-side // 25, side // 25 + 1))
    x, y = max(0, min(side - size, x)), max(0, min(side - size, y))
    alpha = resized[:, :, 3:4] / 255.0
    canvas[y : y + size, x : x + size] = canvas[y : y + size, x : x + size] * (1 - alpha) + resized[:, :, :3] * alpha
    if rng.random() < 0.08:  # the ring a website draws around a piece that can be captured
        overlay = canvas.copy()
        cv2.circle(overlay, (side // 2, side // 2), int(side * 0.47), (0, 0, 0), max(2, side // 12), cv2.LINE_AA)
        canvas = canvas * 0.86 + overlay * 0.14
    canvas = canvas.clip(0, 255).astype(np.uint8)
    if rng.random() < 0.5:
        canvas = cv2.GaussianBlur(canvas, (0, 0), rng.uniform(0.3, 0.9))
    if rng.random() < 0.6:
        ok, encoded = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(45, 95))])
        canvas = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    return canvas


def make_samples(sets: dict[str, dict], per_piece: int, rng: np.random.Generator):
    vectors, labels, owners = [], [], []
    for name, sprites in sets.items():
        for key, sprite in sprites.items():
            for _ in range(per_piece):
                vector = cell_vector(render_cell(sprite, rng))
                if vector is not None:
                    vectors.append(vector)
                    labels.append(KINDS.index(key[1]) + (6 if key[0] == "b" else 0))
                    owners.append(name)
    return np.stack(vectors), np.array(labels), np.array(owners)


def train(x, y, rng, epochs=40, hidden=(256, 128), batch=256, lr=2e-3, weight_decay=1e-4):
    mean, scale = x.mean(axis=0), x.std(axis=0) + 1e-3
    z = (x - mean) / scale
    sizes = [z.shape[1], *hidden, 2 * len(KINDS)]
    params = []
    for a, b in zip(sizes[:-1], sizes[1:]):
        params.append([rng.normal(0, np.sqrt(2 / a), (a, b)).astype(np.float32), np.zeros(b, np.float32)])
    moments = [[np.zeros_like(p), np.zeros_like(p)] for layer in params for p in layer]
    step = 0
    for epoch in range(epochs):
        order = rng.permutation(len(z))
        rate = lr * (0.5 * (1 + np.cos(np.pi * epoch / epochs)))
        for start in range(0, len(z), batch):
            index = order[start : start + batch]
            activations = [z[index] + rng.normal(0, 0.1, z[index].shape).astype(np.float32)]
            masks = []
            for i, (w, b) in enumerate(params):
                out = activations[-1] @ w + b
                if i < len(params) - 1:
                    mask = (rng.random(out.shape) > 0.2) / 0.8  # dropout
                    out = np.maximum(out, 0) * mask
                    masks.append(mask)
                activations.append(out)
            logits = activations[-1] - activations[-1].max(axis=1, keepdims=True)
            p = np.exp(logits)
            p /= p.sum(axis=1, keepdims=True)
            grad = p
            grad[np.arange(len(index)), y[index]] -= 1
            grad /= len(index)
            step += 1
            flat = 0
            for i in reversed(range(len(params))):
                w, b = params[i]
                gw = activations[i].T @ grad + weight_decay * w
                gb = grad.sum(axis=0)
                if i > 0:
                    grad = (grad @ w.T) * (activations[i] > 0) * masks[i - 1]
                for slot, (parameter, g) in enumerate(((w, gw), (b, gb))):
                    m = moments[2 * i + slot]
                    m[0] = 0.9 * m[0] + 0.1 * g
                    m[1] = 0.999 * m[1] + 0.001 * g * g
                    parameter -= rate * (m[0] / (1 - 0.9**step)) / (np.sqrt(m[1] / (1 - 0.999**step)) + 1e-8)
    weights = {"mean": mean.astype(np.float32), "scale": scale.astype(np.float32)}
    for i, (w, b) in enumerate(params):
        weights[f"w{i}"], weights[f"b{i}"] = w, b
    return weights


def accuracy(weights, x, y):
    """Share right for (kind, colour) together; the kind alone and the colour alone are printed too."""
    from piece_classifier import PieceModel

    guess = PieceModel(weights).probabilities(x).argmax(axis=1)
    print(f"     kind {float(((guess % 6) == (y % 6)).mean()):.3f}  colour {float(((guess // 6) == (y // 6)).mean()):.4f}")
    return float((guess == y).mean())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sets")
    parser.add_argument("--hold", default="", help="folder-name prefix of sets kept out of training")
    parser.add_argument("--per", type=int, default=120)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--out", default=str(MODEL_PATH))
    args = parser.parse_args()
    rng = np.random.default_rng(0)
    sets = {folder.name: load_set(folder) for folder in sorted(Path(args.sets).iterdir()) if folder.is_dir()}
    sets = {name: s for name, s in sets.items() if len(s) == 12}
    held = {n: s for n, s in sets.items() if args.hold and n.startswith(tuple(args.hold.split(",")))}
    used = {n: s for n, s in sets.items() if n not in held}
    used.update(glyph_sets())
    print(f"{len(used)} sets to train on, {len(held)} held out")
    x, y, _ = make_samples(used, args.per, rng)
    print("training samples", x.shape)
    weights = train(x, y, rng, epochs=args.epochs)
    print("accuracy on training sets", round(accuracy(weights, x, y), 4))
    if held:
        for name, sprites in held.items():
            hx, hy, _ = make_samples({name: sprites}, 40, rng)
            print(f"  unseen {name}: {accuracy(weights, hx, hy):.3f}")
        hx, hy, _ = make_samples(held, 40, rng)
        print("accuracy on unseen sets", round(accuracy(weights, hx, hy), 4))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, **weights)
    print("saved", args.out)


if __name__ == "__main__":
    main()
