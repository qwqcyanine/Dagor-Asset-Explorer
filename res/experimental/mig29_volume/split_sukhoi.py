"""CLI compatibility entry point; the Glide GUI now uses the shared splitter."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src/dae"))
from util.sourceparts import split, prune_smd

if __name__ == "__main__":
    split(sys.argv[1])
