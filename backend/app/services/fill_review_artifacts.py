import base64
import os
import time
from pathlib import Path
from typing import Optional


class FillReviewArtifactStore:
    """Stores fill-review screenshots and traces under an app-controlled root."""

    @staticmethod
    def root() -> Path:
        return Path(
            os.getenv("FILL_REVIEW_ARTIFACT_DIR", "storage/fill_review_artifacts")
        ).resolve()

    @staticmethod
    def retention_days() -> Optional[int]:
        raw_value = os.getenv("FILL_REVIEW_ARTIFACT_RETENTION_DAYS", "14")
        try:
            days = int(raw_value)
        except (TypeError, ValueError):
            days = 14
        return days if days > 0 else None

    @classmethod
    def prune_expired(cls) -> int:
        retention_days = cls.retention_days()
        if retention_days is None:
            return 0

        root = cls.root()
        if not root.exists():
            return 0

        cutoff = time.time() - (retention_days * 24 * 60 * 60)
        deleted = 0
        for path in root.rglob("*"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    deleted += 1
            except OSError:
                continue

        for path in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
            try:
                path.rmdir()
            except OSError:
                continue
        return deleted

    @classmethod
    def save_base64(
        cls,
        *,
        user_id: int,
        application_id: int,
        review_id: int,
        kind: str,
        payload_base64: Optional[str],
        extension: str,
    ) -> Optional[str]:
        if not payload_base64:
            return None

        try:
            cls.prune_expired()
            data = base64.b64decode(payload_base64, validate=True)
            artifact_dir = cls.root() / str(user_id) / str(application_id)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            path = artifact_dir / f"{review_id}-{kind}.{extension}"
            path.write_bytes(data)
            return str(path)
        except Exception:
            return None

    @classmethod
    def delete(cls, path: Optional[str]) -> None:
        if not path:
            return

        try:
            artifact_path = Path(path).resolve()
            artifact_path.relative_to(cls.root())
            artifact_path.unlink(missing_ok=True)
        except Exception:
            return

    @classmethod
    def is_readable(cls, path: Optional[str]) -> bool:
        if not path:
            return False

        try:
            artifact_path = Path(path).resolve()
            artifact_path.relative_to(cls.root())
            return artifact_path.is_file()
        except Exception:
            return False
