"""Canonical value bytes and IDs, independent of state keys and witnesses.

State Fabric content-addresses value bytes independently from their
authenticated location. The commitment backend binds a state key to those
bytes under a canonical root.
"""

from pathlib import Path

from modules.content_store import content_id, get_content, put_content


DEFAULT_REFERENCE_DIR = Path("data/reference")


def account_state_key(address: str) -> bytes:
    return address.lower().encode("ascii")


def account_value_bytes(balance: int, nonce: int) -> bytes:
    if any(type(value) is not int or value < 0 for value in (balance, nonce)):
        raise ValueError("Balance and nonce must be non-negative integers")
    return f"balance={balance}\nnonce={nonce}\n".encode("ascii")


def read_account_value(peer_dir: Path) -> bytes:
    cache = peer_dir / "cache" / "self"
    return account_value_bytes(
        int((cache / "balance").read_text(encoding="utf-8").strip()),
        int((cache / "nonce").read_text(encoding="utf-8").strip()),
    )


def state_value_id(value_bytes: bytes) -> str:
    """Identify canonical value bytes only; identical values may share one ID."""
    return content_id(value_bytes)


def store_state_value(value_bytes: bytes,
                      reference_dir: Path = DEFAULT_REFERENCE_DIR) -> str:
    return put_content(reference_dir / "state_values", value_bytes)


def load_state_value(object_id: str,
                     reference_dir: Path = DEFAULT_REFERENCE_DIR) -> bytes:
    return get_content(reference_dir / "state_values", object_id)
