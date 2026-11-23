"""export.py — batch export helpers (ZIP of finished clips + sidecars)."""
from __future__ import annotations

import zipfile
from pathlib import Path


def make_zip(files: list[str | Path], zip_path: str | Path) -> Path:
    """Zip the given files (clips and their JSON sidecars) for one
    batch download. Missing files are skipped silently."""
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            p = Path(f)
            if p.exists():
                z.write(p, arcname=p.name)
    return zip_path
