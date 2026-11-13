---
name: r2-upload
description: Uploads files to Cloudflare R2, AWS S3, or any S3-compatible storage and returns a public or temporary URL. Use when you need to publish assets, share files, or provide upload helpers to other skills.
compatibility: Requires Python 3.8+ and PyYAML. Uses AWS SigV4 signing (no external SDK required).
metadata:
  author: foundra
  version: "2.1"
---

# R2 Upload

Upload files to R2/S3-compatible storage and return a URL.

## Quick start (Cloudflare R2)

```bash
# 1. dependency
python3 -m pip install pyyaml

# 2. config -> ~/.r2-upload.yml (chmod 600)
cat > ~/.r2-upload.yml << 'EOF'
default: r2
buckets:
  r2:
    endpoint: https://<account_id>.r2.cloudflarestorage.com
    access_key_id: <R2 access key id>
    secret_access_key: <R2 secret access key>
    bucket_name: <your bucket>
    public_url: https://cdn.example.com
    region: auto
EOF
chmod 600 ~/.r2-upload.yml

# 3. upload
python3 scripts/r2-upload.py ./photo.jpg --public
```

R2 rules that break the signature or the request when wrong:

- `endpoint` is the account-scoped URL with **no bucket path**.
- `region` must be `auto`.
- `public_url` is the CDN domain; presigned URLs use the storage endpoint.

See `references/CONFIGURATION.md` for other S3-compatible providers
(AWS S3, MinIO, Backblaze B2, Wasabi) and multi-bucket setups, and
`references/IMAGES.md` for image key layout and cache-header guidance.


## Use when

- Upload images, documents, or other assets to object storage
- Generate public URLs for web/CDN use
- Generate presigned URLs for temporary access
- Provide upload helpers to other skills (like tech-news)

## Prerequisites

- Python 3.8+ available as `python3`
- PyYAML (`python3 -m pip install pyyaml`)
- Config at `~/.r2-upload.yml` (or set `R2_UPLOAD_CONFIG`)
- Decide the bucket, object key/path, and visibility (public vs presigned)
- If you skip `--key`/`--key-prefix`, the default is `YYYY/MM/DD/<file-name>`

## Recommended workflow

1. Confirm bucket/key and whether the URL should be public or presigned (avoid overwrites unless asked).
2. Verify config and bucket exist.
3. Upload with the CLI (recommended) or Python helper.
4. Return the URL and key; note whether it is public or temporary and the expiration.

## Quick commands

```bash
python3 scripts/r2-upload.py ./photo.jpg --public
python3 scripts/r2-upload.py ./photo.jpg --key images/YYYY/MM/DD/cover.jpg --public
python3 scripts/r2-upload.py ./report.pdf --key reports/YYYY/MM/DD/report.pdf
python3 scripts/r2-upload.py ./image.png --key-prefix images/YYYY/MM/DD --public
python3 scripts/r2-upload.py ./file.zip --expires 600
```

## Key options

- `--bucket <name>`: override the default bucket in config
- `--key <path>`: set the object key/path
- `--key-prefix <prefix>`: prepend prefix to the local filename
- `--public`: return a public URL instead of a presigned URL
- `--expires <seconds>`: presigned URL expiration (1-604800)
- `--config <path>`: use a custom config file
- `--timeout <seconds>`: network timeout
- `--content-type <mime>`: override content type
- `--cache-control <value>`: set Cache-Control header
- `--content-disposition <value>`: set Content-Disposition header

## Behavior notes

- Default behavior returns a presigned URL (temporary access).
- If no key is provided, the default key is `YYYY/MM/DD/<file-name>`.
- `--public` returns a public URL. For private buckets, use presigned URLs instead.
- Presigned URLs always use the storage endpoint (custom CDN domains are for public URLs).

## Programmatic usage

```python
import sys
from pathlib import Path

r2_dir = Path("/path/to/r2-upload")  # update to your local path
sys.path.insert(0, str(r2_dir / "scripts"))

from upload import upload_file, batch_upload, fetch_and_upload

url = upload_file(
    local_path="./image.jpg",
    key="images/YYYY/MM/DD/image.jpg",
    make_public=True
)
```

## Scripts

- `scripts/r2-upload.py`: CLI upload tool
- `scripts/upload.py`: Python helpers (`upload_file`, `batch_upload`, `fetch_and_upload`)

## References

- `references/CONFIGURATION.md` (provider config examples)
- `references/IMAGES.md` (image workflow)
- `references/TROUBLESHOOTING.md` (common errors)
