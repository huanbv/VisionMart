#!/usr/bin/env python
"""Build a SKU-classifier training set from human-confirmed labels.

Where the labels come from
--------------------------
Two sources, both already human-verified — which is the point. Training a
classifier on the detector's own guesses would teach it to repeat its own
mistakes, so nothing enters this dataset without a person having confirmed
the SKU:

* ``ai_review_candidates`` with ``status='approved'`` — frames the model
  was unsure about, corrected by a reviewer. These are the most valuable
  examples precisely because they are the cases the model gets wrong.
* ``ai_training_images`` — products uploaded deliberately for training.

Output is a plain ``ImageFolder`` tree, the format torchvision's training
loop expects:

    out/
      train/AQUAFINA-500/xxx.jpg
      train/LAVIE-500/yyy.jpg
      val/AQUAFINA-500/zzz.jpg
      labels.json          <- index -> SKU, must ship with the model

``labels.json`` is written here rather than by the trainer because the
inference side keys its output purely by index: if the label order ever
disagrees between training and serving, every prediction is silently
mislabelled. Generating it alongside the images keeps one source of truth.

Usage
-----
    python scripts/build_classifier_dataset.py \
        --database-url postgresql://... \
        --minio-endpoint minio:9000 \
        --out /app/training/classifier \
        --val-split 0.2

Dry run (no download, just report what would be collected):
    python scripts/build_classifier_dataset.py --database-url ... --dry-run
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import random
import sys
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("build-classifier-dataset")

# Fewer than this per class and the model will memorise rather than learn;
# better to tell the operator to collect more than to ship a model that
# looks trained but generalises to nothing.
MIN_IMAGES_PER_CLASS = 20
RECOMMENDED_PER_CLASS = 100


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    p.add_argument("--minio-endpoint", default=os.getenv("MINIO_ENDPOINT", "minio:9000"))
    p.add_argument("--minio-access-key", default=os.getenv("MINIO_ROOT_USER", ""))
    p.add_argument("--minio-secret-key", default=os.getenv("MINIO_ROOT_PASSWORD", ""))
    p.add_argument("--minio-bucket", default=os.getenv("MINIO_BUCKET", "visionmart"))
    p.add_argument("--minio-secure", action="store_true")
    p.add_argument("--organization-id", default=None, help="Limit to one organization")
    p.add_argument("--out", default="/app/training/classifier")
    p.add_argument("--val-split", type=float, default=0.2)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--dry-run", action="store_true", help="Report counts, download nothing")
    return p.parse_args()


def collect_labelled_keys(database_url: str, organization_id: str | None) -> dict[str, list[str]]:
    """SKU -> list of object-storage keys, from both human-verified sources."""
    from sqlalchemy import create_engine, text

    # psycopg async URLs are common in this project's env; this script is
    # sync, so normalise the driver rather than failing on it.
    url = database_url.replace("+asyncpg", "").replace("+psycopg_async", "")
    engine = create_engine(url)

    by_sku: dict[str, list[str]] = defaultdict(list)
    org_filter = "AND r.organization_id = :org" if organization_id else ""
    params: dict[str, object] = {}
    if organization_id:
        params["org"] = organization_id

    with engine.connect() as conn:
        approved = conn.execute(
            text(
                f"""
                SELECT p.sku AS sku, r.storage_key AS key
                FROM ai_review_candidates r
                JOIN products p ON p.id = r.confirmed_product_id
                WHERE r.status = 'approved'
                  AND r.is_deleted = false
                  AND r.storage_key IS NOT NULL
                  {org_filter}
                """
            ),
            params,
        ).mappings().all()
        for row in approved:
            by_sku[str(row["sku"])].append(str(row["key"]))
        logger.info("review queue (approved): %d images", len(approved))

        org_filter_t = "AND t.organization_id = :org" if organization_id else ""
        uploaded = conn.execute(
            text(
                f"""
                SELECT p.sku AS sku, t.storage_key AS key
                FROM ai_training_images t
                JOIN products p ON p.id = t.product_id
                WHERE t.is_deleted = false
                  {org_filter_t}
                """
            ),
            params,
        ).mappings().all()
        for row in uploaded:
            by_sku[str(row["sku"])].append(str(row["key"]))
        logger.info("uploaded training images: %d", len(uploaded))

    # De-duplicate: an approved review frame is stored once but could be
    # referenced by both queries if it was also promoted to a TrainingImage.
    return {sku: sorted(set(keys)) for sku, keys in by_sku.items()}


def main() -> int:
    args = parse_args()
    if not args.database_url:
        logger.error("--database-url (or DATABASE_URL) is required")
        return 2

    random.seed(args.seed)
    by_sku = collect_labelled_keys(args.database_url, args.organization_id)
    if not by_sku:
        logger.error(
            "No human-confirmed labels found. Approve items in the review "
            "queue (Duyệt dữ liệu AI) or upload training images first."
        )
        return 1

    # Report before doing any work — an operator usually runs this to find
    # out whether there is *enough* data yet.
    usable: dict[str, list[str]] = {}
    logger.info("--- label inventory ---")
    for sku in sorted(by_sku):
        keys = by_sku[sku]
        if len(keys) < MIN_IMAGES_PER_CLASS:
            logger.warning(
                "%-24s %4d images — SKIPPED (need >= %d)",
                sku, len(keys), MIN_IMAGES_PER_CLASS,
            )
            continue
        flag = "" if len(keys) >= RECOMMENDED_PER_CLASS else "  (thin: aim for %d+)" % RECOMMENDED_PER_CLASS
        logger.info("%-24s %4d images%s", sku, len(keys), flag)
        usable[sku] = keys

    if len(usable) < 2:
        logger.error(
            "Need at least 2 classes with >= %d images each; got %d. "
            "A one-class classifier cannot be trained.",
            MIN_IMAGES_PER_CLASS, len(usable),
        )
        return 1

    labels = sorted(usable)
    total = sum(len(v) for v in usable.values())
    logger.info("%d classes, %d images total", len(labels), total)

    if args.dry_run:
        logger.info("--dry-run: nothing downloaded")
        return 0

    from minio import Minio

    client = Minio(
        args.minio_endpoint,
        access_key=args.minio_access_key,
        secret_key=args.minio_secret_key,
        secure=args.minio_secure,
    )

    for split in ("train", "val"):
        for sku in labels:
            os.makedirs(os.path.join(args.out, split, sku), exist_ok=True)

    downloaded = failed = 0
    for sku in labels:
        keys = list(usable[sku])
        random.shuffle(keys)
        # Guarantee at least one validation image per class, otherwise the
        # class silently has no val signal and accuracy is unmeasurable.
        n_val = max(1, int(len(keys) * args.val_split))
        for i, key in enumerate(keys):
            split = "val" if i < n_val else "train"
            ext = os.path.splitext(key)[1] or ".jpg"
            dest = os.path.join(args.out, split, sku, f"{i:05d}{ext}")
            try:
                resp = client.get_object(args.minio_bucket, key)
                try:
                    data = resp.read()
                finally:
                    resp.close()
                    resp.release_conn()
                with open(dest, "wb") as fh:
                    fh.write(data)
                downloaded += 1
            except Exception:
                # One unreadable object must not abort a long download.
                logger.warning("could not fetch %s", key, exc_info=True)
                failed += 1

    labels_path = os.path.join(args.out, "labels.json")
    with open(labels_path, "w", encoding="utf-8") as fh:
        json.dump(labels, fh, ensure_ascii=False, indent=2)

    logger.info("downloaded=%d failed=%d", downloaded, failed)
    logger.info("labels written to %s (ship this WITH the model)", labels_path)
    logger.info("dataset ready at %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
