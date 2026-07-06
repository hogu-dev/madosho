from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO


class FileStore:
    """Local-directory file store behind a tiny put/resolve seam.

    Layout: <base>/<content_hash>/<filename>. The seam (put_stream/path_for)
    is what a later obstore/S3 backend slots into without touching callers."""

    CHUNK = 1024 * 1024  # 1 MiB

    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def put_stream(self, filename: str, fileobj: BinaryIO) -> tuple[str, str]:
        """Stream fileobj into storage. Returns (uri, content_hash)."""
        # filename comes from an upload header (user-controlled); collapse it to
        # a bare basename so it can't traverse out of the store dir. Degenerate
        # names (e.g. "..", "") fall back to "upload".
        safe_name = Path(filename).name or "upload"

        incoming = self.base / ".incoming"
        incoming.mkdir(exist_ok=True)
        staging = incoming / f"{uuid.uuid4().hex}-{safe_name}"

        try:
            h = hashlib.sha256()
            with open(staging, "wb") as out:
                while chunk := fileobj.read(self.CHUNK):
                    h.update(chunk)
                    out.write(chunk)
            digest = h.hexdigest()
            dest_dir = self.base / digest
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / safe_name
            shutil.move(str(staging), str(dest))
            return f"{digest}/{safe_name}", digest
        finally:
            staging.unlink(missing_ok=True)  # remove orphan if we failed before the move

    def path_for(self, uri: str) -> Path:
        return self.base / uri
