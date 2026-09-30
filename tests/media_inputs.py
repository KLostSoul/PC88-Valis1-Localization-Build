import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def original_media(kind: str) -> Path:
    baseline = json.loads((ROOT / "source/release-baseline.json").read_text(encoding="utf-8"))["input"]
    prefix = "d88" if kind == "d88" else "kanji1"
    override = os.environ.get("VALIS_ORIGINAL_D88" if kind == "d88" else "VALIS_ORIGINAL_ROM")
    candidates = [Path(override)] if override else sorted((ROOT / "import").glob("*"))
    for path in candidates:
        if path.is_file() and path.stat().st_size == baseline[f"{prefix}_size"]:
            if hashlib.sha256(path.read_bytes()).hexdigest() == baseline[f"{prefix}_sha256"]:
                return path
    if override:
        raise ValueError(f"original {kind} override does not match the baseline")
    return ROOT / "import" / f".missing-{kind}"
