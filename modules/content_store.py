"""Opaque content-addressed bytes shared by state values and commitment nodes."""

from pathlib import Path

from eth_utils import keccak


def content_id(data: bytes) -> str:
    return f"0x{keccak(data).hex()}"


def content_path(directory: Path, object_id: str) -> Path:
    return directory / f"{object_id.removeprefix('0x')}.bin"


def put_content(directory: Path, data: bytes) -> str:
    object_id = content_id(data)
    path = content_path(directory, object_id)
    directory.mkdir(parents=True, exist_ok=True)
    if path.exists():
        get_content(directory, object_id)
    else:
        path.write_bytes(data)
    return object_id


def get_content(directory: Path, object_id: str) -> bytes:
    data = content_path(directory, object_id).read_bytes()
    if content_id(data) != object_id:
        raise ValueError(f"Content hash mismatch: {object_id}")
    return data
