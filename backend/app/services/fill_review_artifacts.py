import base64
import os
from pathlib import Path
from typing import Optional


class FillReviewArtifactStore:
    """Stores fill-review screenshots and traces under an app-controlled root."""

    @staticmethod
    def root() -> Path:
        return Path(
            os.getenv("FILL_REVIEW_ARTIFACT_DIR", "storage/fill_review_artifacts")
        ).resolve()

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
