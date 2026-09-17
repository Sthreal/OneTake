from dataclasses import dataclass


@dataclass(frozen=True)
class PresignUploadCommand:
    original_filename: str
    mime_type: str
    size_bytes: int
    width: int
    height: int
    sha256: str | None = None


@dataclass(frozen=True)
class CompleteUploadCommand:
    original_filename: str
    mime_type: str
    size_bytes: int
    width: int
    height: int
    sha256: str