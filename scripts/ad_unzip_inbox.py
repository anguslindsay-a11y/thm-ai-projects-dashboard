"""
Unzip dropped OneDrive_*.zip files in THM Ads/ into their canonical folder names.

Each zip contains a root folder like 'THM Utah 2026-03'. We extract to
THM Ads/{that folder}/, skip if the target already exists (duplicate), and move
the processed zip to THM Ads/_processed/ when done.

Safe to re-run — already-extracted zips are moved to _processed and won't be
touched again.
"""

import re
import shutil
import sys
import zipfile
from pathlib import Path
from collections import Counter

ADS_ROOT = Path(r"C:\Users\MasenSpring\OneDrive - TheHomeMagWest\Supabase Data Hub\THM Ads")
PROCESSED = ADS_ROOT / "_processed"
PROCESSED.mkdir(exist_ok=True)

CANONICAL_RE = re.compile(r"^THM [A-Za-z]+ \d{4}-\d{2}s?/?")


def canonical_folder(names: list[str]) -> str | None:
    """Find the canonical folder name inside a zip (e.g. 'THM Utah 2026-03')."""
    counts = Counter()
    for n in names:
        # strip leading underscores or whitespace
        first = n.split("/", 1)[0].lstrip("_ ")
        # match "THM State YYYY-MM[s]"
        m = re.match(r"^(THM [A-Za-z]+ \d{4}-\d{2}s?)$", first)
        if m:
            counts[m.group(1)] += 1
    if counts:
        return counts.most_common(1)[0][0]
    # fallback: look for it inside file paths
    for n in names:
        m = re.match(r"^(?:_*)?((?:THM [A-Za-z]+ \d{4}-\d{2}s?))/", n)
        if m:
            return m.group(1)
    return None


def extract_zip(zip_path: Path) -> tuple[str, int, str]:
    """Returns (target_folder_name, files_extracted, status)."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        target = canonical_folder(names)
        if not target:
            return ("?", 0, "no canonical folder detected")
        target_dir = ADS_ROOT / target
        if target_dir.exists() and any(target_dir.iterdir()):
            return (target, 0, "already exists — skipping")
        target_dir.mkdir(exist_ok=True)

        extracted = 0
        for n in names:
            if n.endswith("/"):
                continue
            # Normalize: strip leading junk ('__' prefix), normalize path
            normalized = re.sub(r"^_*", "", n)
            # If normalized starts with target, extract as-is; else rewrite under target
            if normalized.startswith(target + "/"):
                rel = normalized[len(target) + 1 :]
            else:
                # drop first path segment entirely, keep rest
                parts = normalized.split("/", 1)
                rel = parts[1] if len(parts) > 1 else normalized
            if not rel:
                continue
            out_path = target_dir / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Skip if output already there (partial prior run)
            if out_path.exists():
                continue
            with zf.open(n) as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted += 1
    return (target, extracted, "ok")


def main():
    zips = sorted(ADS_ROOT.glob("OneDrive_*.zip"))
    if not zips:
        print("No OneDrive_*.zip files found in THM Ads/")
        return

    print(f"Found {len(zips)} zip files\n")
    for z in zips:
        try:
            target, count, status = extract_zip(z)
            print(f"  {z.name:<45}  ->  {target or '?':<28}  {count:>4} files  [{status}]")
            # Move processed zip
            dest = PROCESSED / z.name
            if dest.exists():
                dest.unlink()
            shutil.move(str(z), str(dest))
        except Exception as e:
            print(f"  {z.name:<45}  ERROR: {e}")

    print(f"\nDone. Zips moved to {PROCESSED}")


if __name__ == "__main__":
    main()
