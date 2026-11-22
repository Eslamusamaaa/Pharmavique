"""Upload the product pictures that belong to a drug to the public bucket (Neon object storage).

    uv run --with boto3 python scripts/upload_pictures_to_bucket.py [--limit N] [--bucket pharmavique]

Reads the S3 settings (AWS_ENDPOINT_URL_S3, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION)
from the environment or from `.env.neon-storage` (git-ignored). Only pictures that the mapping
(`data/media/mapping.jsonl`) links to a drug are uploaded, under the same key the API uses
(`products/SA/<register>/<file>`, see `picture_key`). Safe to repeat: files already in the bucket
with the same size are skipped.
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pharmavique.bootstrap.api_pictures import picture_key  # noqa: E402


def load_env(path: Path) -> None:
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                name, value = line.split("=", 1)
                os.environ.setdefault(name.strip(), value.strip().strip('"'))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", default="pharmavique")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()
    load_env(ROOT / ".env.neon-storage")
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["AWS_ENDPOINT_URL_S3"],
        region_name=os.environ.get("AWS_REGION", "eu-central-1"),
        config=boto3.session.Config(s3={"addressing_style": "path"}, retries={"max_attempts": 5}),
    )
    rows = [
        json.loads(x)
        for x in (ROOT / "data/media/mapping.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    wanted: dict[str, tuple[Path, str]] = {}
    missing = 0
    for row in rows:
        if row["picture_kind"] != "real":
            continue
        key = picture_key(row["picture"])
        path = ROOT / row["picture"].replace("\\", "/")
        if key is None or not path.is_file():
            missing += 1
            continue
        content_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}.get(path.suffix.lstrip(".").lower(), "application/octet-stream")
        wanted[key] = (path, content_type)
    items = list(wanted.items())[: args.limit or None]
    print(f"{len(items)} pictures to check ({missing} mapped pictures have no file here)", flush=True)

    def upload(item: tuple[str, tuple[Path, str]]) -> str:
        key, (path, content_type) = item
        size = path.stat().st_size
        try:
            if s3.head_object(Bucket=args.bucket, Key=key)["ContentLength"] == size:
                return "skipped"
        except ClientError:
            pass
        s3.upload_file(
            str(path), args.bucket, key,
            ExtraArgs={"ContentType": content_type, "CacheControl": "public, max-age=31536000, immutable"},
        )
        return "uploaded"

    counts: dict[str, int] = {}
    with ThreadPoolExecutor(args.threads) as pool:
        for n, result in enumerate(pool.map(upload, items), 1):
            counts[result] = counts.get(result, 0) + 1
            if n % 250 == 0:
                print(f"{n}/{len(items)} {counts}", flush=True)
    print(f"done: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
