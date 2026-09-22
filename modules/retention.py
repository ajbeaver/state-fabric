"""Temporary Phase 2 protection policy, separate from canonical ordering and custody."""

from dataclasses import dataclass
from pathlib import Path

from modules.canonical_history import canonical_source


DEFAULT_PEERS_DIR = Path("data/peers")
DEFAULT_REFERENCE_DIR = Path("data/reference")


@dataclass(frozen=True)
class ProtectionDecision:
    protected: bool
    role: str


def should_protect(
    object_version: dict,
    canonical_versions: list[dict],
    replacement_recoverable: bool,
) -> ProtectionDecision:
    """Protect the latest and previous versions; retire older ones only after recovery."""
    if not canonical_versions:
        raise ValueError("No canonical versions exist for this address")

    current = canonical_versions[-1]
    if object_version["object_id"] == current["object_id"]:
        return ProtectionDecision(True, "current")

    if (len(canonical_versions) > 1
            and object_version["object_id"] == canonical_versions[-2]["object_id"]):
        return ProtectionDecision(True, "fallback")

    if not replacement_recoverable:
        return ProtectionDecision(True, "awaiting-recoverable-replacement")

    return ProtectionDecision(False, "historical")


def object_health(object_id: str, peers_dir: Path = DEFAULT_PEERS_DIR) -> tuple[int, dict, str]:
    """Return valid active fragment count and a usable local view for an object."""
    from modules.custody import get_valid_active_fragments, load_network_metadata

    best: tuple[int, dict, str] | None = None
    if not peers_dir.exists():
        raise ValueError("Peers directory does not exist")
    for peer_dir in sorted(peers_dir.iterdir(), key=lambda path: path.name.lower()):
        if not (peer_dir / "data" / object_id / "custody.json").is_file():
            continue
        _, manifest, custody = load_network_metadata(object_id, peer_dir.name, peers_dir)
        count = len(get_valid_active_fragments(object_id, manifest, custody, peers_dir))
        if best is None or count > best[0]:
            best = (count, manifest, peer_dir.name)
    if best is None:
        raise ValueError(f"No distributed custody for object: {object_id}")
    return best


def independently_recoverable(object_id: str, peers_dir: Path = DEFAULT_PEERS_DIR) -> bool:
    from modules.custody import reconstruct_from_network

    try:
        count, manifest, peer = object_health(object_id, peers_dir)
        if count < manifest["encoding"]["required_fragments"]:
            return False
        reconstruct_from_network(object_id, peer, peers_dir)
        return True
    except (ValueError, OSError, KeyError):
        return False


def protection_for_object(
    object_id: str,
    peers_dir: Path = DEFAULT_PEERS_DIR,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> ProtectionDecision:
    source = canonical_source(reference_dir)
    version = source.version_for_object(object_id)
    versions = source.versions(version["address"])
    current_id = versions[-1]["object_id"]
    replacement_ready = (
        True if object_id == current_id
        else independently_recoverable(current_id, peers_dir)
    )
    return should_protect(version, versions, replacement_ready)


def repair_required(
    object_id: str,
    peers_dir: Path = DEFAULT_PEERS_DIR,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> bool:
    if not protection_for_object(object_id, peers_dir, reference_dir).protected:
        return False
    count, manifest, _ = object_health(object_id, peers_dir)
    return count < manifest["encoding"]["total_fragments"]
