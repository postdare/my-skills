# Image Workflow

Upload images and get URLs back. The two entry points are the CLI
(`scripts/r2-upload.py`) and the Python helpers in `scripts/upload.py`.

## Typical image flow

1. Pick the bucket and the key. Keep images under a date or slug prefix so
   the bucket stays browsable:

   ```bash
   python3 scripts/r2-upload.py ./cover.png --key images/2026/02/05/cover.png --public
   ```

2. Choose visibility deliberately:
   - `--public` for assets served from a CDN domain (referenced by web pages).
   - default (no flag) for a presigned URL, when only a short-lived consumer
     needs the file.

3. Set the cache headers your CDN expects, so re-uploads are picked up:

   ```bash
   python3 scripts/r2-upload.py ./cover.png      --key images/2026/02/05/cover.png      --public      --cache-control "public, max-age=31536000, immutable"
   ```

   Use an immutable path (a content hash or a dated slug) whenever you set a
   long max-age. Otherwise a client keeps the old image after you overwrite
   the same key.

## Key layout

| Purpose | Key pattern |
|---|---|
| Dated assets | `images/YYYY/MM/DD/<name>` |
| Slug-based, overwriteable | `images/<slug>.png` |
| Content-addressed (immutable) | `images/<sha256[:16]>.png` |

The default key when `--key` is omitted is `YYYY/MM/DD/<local filename>`,
using the local date.

## Batch upload

`batch_upload` in `scripts/upload.py` uploads many local files under one
prefix and returns a list of URLs:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path("/path/to/r2-upload") / "scripts"))
from upload import batch_upload

urls = batch_upload(
    ["a.png", "b.png", "c.png"],
    key_prefix="images/2026/02/05",
    make_public=True,
)
```

The CLI has no batch mode; call the helper directly for that.

## Fetch a remote image and re-host it

`fetch_and_upload` downloads a remote file and uploads it in one step. It
picks up the source `Content-Type` unless you override it:

```python
from upload import fetch_and_upload

url = fetch_and_upload(
    "https://example.com/original.png",
    key="images/2026/02/05/original.png",
    make_public=True,
)
```

Useful for mirroring an upstream image into your own bucket and CDN.

## Content types

`_guess_content_type` uses `mimetypes.guess_type` first, then falls back to
a small extension map (`.jpg`, `.png`, `.webp`, `.svg`, `.pdf`, `.md`,
`.yml`, `.json`, `.txt`), and finally `application/octet-stream`.
Override it when the guess is wrong:

```bash
--content-type image/avif
```

## R2 notes

- `region: auto` is correct for R2. Any other region value makes R2 reject
  the signature.
- The endpoint is the account-scoped URL
  `https://<account_id>.r2.cloudflarestorage.com` with **no bucket path**.
- For a public bucket, set `public_url` to your custom domain. Presigned URLs
  always use the storage endpoint, never the CDN domain.
- R2 does not charge egress, so a public URL is usually the cheaper default
  for images that appear on a public site.
