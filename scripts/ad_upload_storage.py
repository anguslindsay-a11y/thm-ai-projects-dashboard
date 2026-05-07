"""
Upload all THM Ads JPGs to Supabase Storage bucket 'client_ads'.

Resumable — skips files that already exist in the bucket.
Uses concurrent uploads (default 8 workers) to speed things up.
"""

import os
import sys
import time
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv(override=True)

from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BUCKET = "client_ads"
ADS_ROOT = Path(r"C:\Users\MasenSpring\OneDrive - TheHomeMagWest\Supabase Data Hub\THM Ads")
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def ensure_bucket(sb: Client) -> None:
    """Create bucket if it doesn't exist."""
    try:
        existing = sb.storage.list_buckets()
        names = [b.name for b in existing]
    except Exception as e:
        print(f"Error listing buckets: {e}")
        names = []
    if BUCKET in names:
        print(f"Bucket '{BUCKET}' exists.")
        return
    try:
        sb.storage.create_bucket(
            BUCKET,
            options={"public": False, "file_size_limit": 10 * 1024 * 1024},  # 10 MB cap
        )
        print(f"Created bucket '{BUCKET}'.")
    except Exception as e:
        print(f"Error creating bucket: {e}")
        raise


def discover_ads() -> list[Path]:
    return sorted(p for p in ADS_ROOT.rglob("*") if p.suffix.lower() in IMAGE_EXTS)


def list_existing_paths(sb: Client) -> set[str]:
    """Recursively list all objects in the bucket."""
    existing = set()

    def walk(prefix: str = ""):
        try:
            items = sb.storage.from_(BUCKET).list(prefix or None, {"limit": 10000})
        except Exception as e:
            print(f"  Error listing '{prefix}': {e}")
            return
        for item in items:
            name = item["name"]
            full = f"{prefix}/{name}" if prefix else name
            # heuristic: items without "id" or with metadata==None could be folders
            if item.get("id") is None:
                walk(full)
            else:
                existing.add(full)

    walk("")
    return existing


import threading
_thread_local = threading.local()

def _get_thread_client() -> Client:
    if not hasattr(_thread_local, "sb"):
        _thread_local.sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _thread_local.sb


def upload_one(path: Path) -> tuple[str, bool, str]:
    relpath = str(path.relative_to(ADS_ROOT)).replace("\\", "/")
    media = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(
        path.suffix.lower().lstrip("."), "image/jpeg"
    )
    try:
        sb = _get_thread_client()
        with open(path, "rb") as f:
            data = f.read()
        sb.storage.from_(BUCKET).upload(
            path=relpath,
            file=data,
            file_options={"content-type": media},
        )
        return (relpath, True, "")
    except Exception as e:
        msg = str(e)
        if "already exists" in msg.lower() or "duplicate" in msg.lower() or "409" in msg:
            return (relpath, True, "existed")
        return (relpath, False, msg[:200])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    ensure_bucket(sb)

    all_ads = discover_ads()
    print(f"Discovered {len(all_ads)} local ads")

    print("Listing existing objects in bucket...")
    existing = list_existing_paths(sb)
    print(f"  {len(existing)} already uploaded")

    todo = [p for p in all_ads if str(p.relative_to(ADS_ROOT)).replace("\\", "/") not in existing]
    if args.limit:
        todo = todo[: args.limit]
    print(f"To upload: {len(todo)}")
    if not todo:
        print("Nothing to do.")
        return

    start = time.time()
    ok = err = 0
    errors = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(upload_one, p): p for p in todo}
        for fut in as_completed(futures):
            relpath, success, msg = fut.result()
            if success:
                ok += 1
            else:
                err += 1
                errors.append((relpath, msg))
            done = ok + err
            if done % 50 == 0 or done == len(todo):
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(todo) - done) / rate if rate > 0 else 0
                print(f"  [{done:4}/{len(todo)}] ok={ok} err={err} rate={rate:.1f}/s eta={eta/60:.1f}min")

    print(f"\nDone in {(time.time()-start)/60:.1f} min. ok={ok} err={err}")
    if errors[:10]:
        print("First errors:")
        for r, m in errors[:10]:
            print(f"  {r}: {m}")


if __name__ == "__main__":
    main()
