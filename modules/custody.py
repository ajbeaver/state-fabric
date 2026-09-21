import json
import shutil

from datetime import datetime, timedelta, timezone
from pathlib import Path

from eth_utils import keccak

from modules.merkle import find_peer_dir
from modules.peers import can_accept
from modules.storage import (
    erasure_decode_2_of_5,
    erasure_encode_2_of_5,
    get_object_id,
    load_manifest,
    parse_state_package,
    verify_state_package,
)

DEFAULT_PEERS_DIR = Path("data/peers")

DEFAULT_RESERVATION_SECONDS = 60
DEFAULT_LEASE_SECONDS = 24 * 60 * 60


def utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def format_time(
    value: datetime,
) -> str:
    return (
        value
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_time(
    value: str,
) -> datetime:
    return datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00",
        )
    )


def get_leases_path(
    offer_dir: Path,
) -> Path:
    return (
        offer_dir
        / "leases.json"
    )


def load_leases(
    offer_dir: Path,
) -> dict:
    leases_path = get_leases_path(
        offer_dir
    )

    if not leases_path.exists():
        return {}

    return json.loads(
        leases_path.read_text(
            encoding="utf-8"
        )
    )


def save_leases(
    offer_dir: Path,
    leases: dict,
) -> None:
    leases_path = get_leases_path(
        offer_dir
    )

    leases_path.write_text(
        json.dumps(
            leases,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def replicate_custody_view(
    offer_dir: Path,
    object_id: str,
    leases: dict,
) -> None:
    custody = {
        fragment_key: lease
        for fragment_key, lease in sorted(
            leases.items(),
            key=lambda item: int(item[0]),
        )
        if lease["status"] == "leased"
    }

    peers_dir = (
        offer_dir
        .parent
        .parent
        .parent
    )

    for lease in custody.values():
        custodian_dir = find_peer_dir(
            lease["custodian"],
            peers_dir,
        )

        custody_path = (
            custodian_dir
            / "data"
            / object_id
            / "custody.json"
        )

        custody_path.write_text(
            json.dumps(
                custody,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def expire_leases(
    offer_dir: Path,
    now: datetime | None = None,
) -> list[int]:
    if now is None:
        now = utc_now()

    leases = load_leases(
        offer_dir
    )

    expired = []

    for fragment_key, lease in list(
        leases.items()
    ):
        expires_at = parse_time(
            lease["expires_at"]
        )

        if expires_at <= now:
            expired.append(
                int(fragment_key)
            )

            del leases[
                fragment_key
            ]

    if expired:
        save_leases(
            offer_dir,
            leases,
        )

    return expired


def custodian_has_fragment(
    leases: dict,
    custodian_address: str,
) -> bool:
    for lease in leases.values():
        if (
            lease["custodian"].lower()
            == custodian_address.lower()
        ):
            return True

    return False


def get_manifest_fragment(
    manifest: dict,
    fragment_index: int,
) -> dict:
    for fragment in manifest["fragments"]:
        if fragment["index"] == fragment_index:
            return fragment

    raise ValueError(
        f"Fragment not found in manifest: "
        f"{fragment_index}"
    )


def find_offer_dir(
    publisher_dir: Path,
    object_id: str | None = None,
) -> Path:
    offers_dir = (
        publisher_dir
        / "offers"
    )

    if not offers_dir.exists():
        raise ValueError(
            f"No offers found for "
            f"{publisher_dir.name}"
        )

    if object_id:
        offer_dir = (
            offers_dir
            / object_id
        )

        if not offer_dir.exists():
            raise ValueError(
                f"Offer not found: "
                f"{object_id}"
            )

        return offer_dir

    offers = sorted(
        (
            path
            for path
            in offers_dir.iterdir()
            if path.is_dir()
        ),
        key=lambda path: path.name,
    )

    if not offers:
        raise ValueError(
            f"No offers found for "
            f"{publisher_dir.name}"
        )

    if len(offers) > 1:
        raise ValueError(
            "Multiple offers found. "
            "Specify an object ID."
        )

    return offers[0]
    

def write_local_lease_receipt(
    custodian_dir: Path,
    object_id: str,
    publisher_address: str,
    fragment_index: int,
    started_at: str,
    expires_at: str,
) -> Path:
    object_dir = (
        custodian_dir
        / "data"
        / object_id
    )

    object_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    receipt_path = (
        object_dir
        / "lease.json"
    )

    receipt = {
        "publisher": publisher_address,
        "fragment_index": fragment_index,
        "started_at": started_at,
        "expires_at": expires_at,
    }

    receipt_path.write_text(
        json.dumps(
            receipt,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return receipt_path


def reserve_fragment(
    offer_dir: Path,
    custodian_dir: Path,
    reservation_seconds: int = (
        DEFAULT_RESERVATION_SECONDS
    ),
) -> dict:
    expire_leases(
        offer_dir
    )

    manifest = load_manifest(
        offer_dir
    )

    leases = load_leases(
        offer_dir
    )

    if custodian_has_fragment(
        leases,
        custodian_dir.name,
    ):
        raise ValueError(
            f"{custodian_dir.name} already "
            "has an active reservation or lease "
            "for this object"
        )

    selected = None

    for fragment in sorted(
        manifest["fragments"],
        key=lambda item: item["index"],
    ):
        fragment_key = str(
            fragment["index"]
        )

        if fragment_key in leases:
            continue

        if not can_accept(
            custodian_dir,
            fragment["size"],
        ):
            continue

        selected = fragment
        break

    if selected is None:
        raise ValueError(
            "No available fragment can be "
            "accepted by this custodian"
        )

    now = utc_now()

    expires_at = (
        now
        + timedelta(
            seconds=reservation_seconds
        )
    )

    fragment_key = str(
        selected["index"]
    )

    leases[fragment_key] = {
        "custodian": (
            custodian_dir.name
        ),
        "status": "reserved",
        "started_at": format_time(
            now
        ),
        "expires_at": format_time(
            expires_at
        ),
    }

    save_leases(
        offer_dir,
        leases,
    )

    return selected


def release_reservation(
    offer_dir: Path,
    fragment_index: int,
    custodian_address: str,
) -> None:
    leases = load_leases(
        offer_dir
    )

    fragment_key = str(
        fragment_index
    )

    lease = leases.get(
        fragment_key
    )

    if lease is None:
        return

    if (
        lease["custodian"].lower()
        != custodian_address.lower()
    ):
        return

    if lease["status"] != "reserved":
        return

    del leases[
        fragment_key
    ]

    save_leases(
        offer_dir,
        leases,
    )


def confirm_custody(
    offer_dir: Path,
    custodian_dir: Path,
    fragment_index: int,
    lease_seconds: int = (
        DEFAULT_LEASE_SECONDS
    ),
) -> Path:
    expire_leases(
        offer_dir
    )

    manifest = load_manifest(
        offer_dir
    )

    leases = load_leases(
        offer_dir
    )

    fragment_key = str(
        fragment_index
    )

    lease = leases.get(
        fragment_key
    )

    if lease is None:
        raise ValueError(
            "Fragment is not currently reserved"
        )

    if lease["status"] != "reserved":
        raise ValueError(
            "Fragment is not in reserved state"
        )

    if (
        lease["custodian"].lower()
        != custodian_dir.name.lower()
    ):
        raise ValueError(
            "Fragment is reserved for "
            "a different custodian"
        )

    fragment = get_manifest_fragment(
        manifest,
        fragment_index,
    )

    source_path = (
        offer_dir
        / "fragments"
        / fragment["filename"]
    )

    if not source_path.exists():
        release_reservation(
            offer_dir,
            fragment_index,
            custodian_dir.name,
        )

        raise ValueError(
            f"Source fragment missing: "
            f"{fragment['filename']}"
        )

    if not can_accept(
        custodian_dir,
        fragment["size"],
    ):
        release_reservation(
            offer_dir,
            fragment_index,
            custodian_dir.name,
        )

        raise ValueError(
            "Custodian no longer has "
            "enough capacity"
        )

    object_id = manifest[
        "object_id"
    ]

    publisher_address = (
        offer_dir
        .parent
        .parent
        .name
    )

    destination_dir = (
        custodian_dir
        / "data"
        / object_id
    )

    destination_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination_path = (
        destination_dir
        / fragment["filename"]
    )

    receipt_path = (
        destination_dir
        / "lease.json"
    )

    manifest_path = (
        destination_dir
        / "manifest.json"
    )

    try:
        shutil.copyfile(
            source_path,
            destination_path,
        )

        copied = (
            destination_path
            .read_bytes()
        )

        if len(copied) != fragment["size"]:
            raise ValueError(
                "Copied fragment size mismatch"
            )

        copied_hash = (
            f"0x{keccak(copied).hex()}"
        )

        if copied_hash != fragment["hash"]:
            raise ValueError(
                "Copied fragment hash mismatch"
            )

        shutil.copyfile(
            offer_dir / "manifest.json",
            manifest_path,
        )

        now = utc_now()

        expires_at = (
            now
            + timedelta(
                seconds=lease_seconds
            )
        )

        started_at_text = format_time(
            now
        )

        expires_at_text = format_time(
            expires_at
        )

        lease_record = {
            "custodian": (
                custodian_dir.name
            ),
            "status": "leased",
            "started_at": (
                started_at_text
            ),
            "expires_at": (
                expires_at_text
            ),
        }

        write_local_lease_receipt(
            custodian_dir=(
                custodian_dir
            ),
            object_id=(
                object_id
            ),
            publisher_address=(
                publisher_address
            ),
            fragment_index=(
                fragment_index
            ),
            started_at=(
                started_at_text
            ),
            expires_at=(
                expires_at_text
            ),
        )

        leases = load_leases(
            offer_dir
        )

        leases[fragment_key] = (
            lease_record
        )

        save_leases(
            offer_dir,
            leases,
        )

        replicate_custody_view(
            offer_dir,
            object_id,
            leases,
        )

    except Exception:
        if destination_path.exists():
            destination_path.unlink()

        if receipt_path.exists():
            receipt_path.unlink()

        if manifest_path.exists():
            manifest_path.unlink()

        release_reservation(
            offer_dir,
            fragment_index,
            custodian_dir.name,
        )

        raise

    return destination_path
    

def request_custody(
    publisher_address: str,
    custodian_address: str,
    object_id: str | None = None,
    peers_dir: Path = DEFAULT_PEERS_DIR,
    reservation_seconds: int = (
        DEFAULT_RESERVATION_SECONDS
    ),
    lease_seconds: int = (
        DEFAULT_LEASE_SECONDS
    ),
) -> dict:
    if (
        publisher_address.lower()
        == custodian_address.lower()
    ):
        raise ValueError(
            "Publisher cannot custody "
            "its own offered fragment"
        )

    publisher_dir = find_peer_dir(
        publisher_address,
        peers_dir,
    )

    custodian_dir = find_peer_dir(
        custodian_address,
        peers_dir,
    )

    offer_dir = find_offer_dir(
        publisher_dir,
        object_id,
    )

    fragment = reserve_fragment(
        offer_dir,
        custodian_dir,
        reservation_seconds=(
            reservation_seconds
        ),
    )

    destination_path = (
        confirm_custody(
            offer_dir,
            custodian_dir,
            fragment["index"],
            lease_seconds=(
                lease_seconds
            ),
        )
    )

    manifest = load_manifest(
        offer_dir
    )

    leases = load_leases(
        offer_dir
    )

    lease = leases[
        str(fragment["index"])
    ]

    return {
        "object_id": (
            manifest["object_id"]
        ),
        "fragment_index": (
            fragment["index"]
        ),
        "fragment_filename": (
            fragment["filename"]
        ),
        "fragment_size": (
            fragment["size"]
        ),
        "publisher": (
            publisher_dir.name
        ),
        "custodian": (
            custodian_dir.name
        ),
        "destination": str(
            destination_path
        ),
        "lease": lease,
    }


def reconstruct_from_custody(
    publisher_address: str,
    object_id: str | None = None,
    peers_dir: Path = DEFAULT_PEERS_DIR,
) -> bytes:
    publisher_dir = find_peer_dir(
        publisher_address,
        peers_dir,
    )

    offer_dir = find_offer_dir(
        publisher_dir,
        object_id,
    )

    expire_leases(
        offer_dir
    )

    manifest = load_manifest(
        offer_dir
    )

    leases = load_leases(
        offer_dir
    )

    encoding = manifest[
        "encoding"
    ]

    if encoding["type"] != "reed-solomon":
        raise ValueError(
            "Custody reconstruction currently "
            "supports erasure-coded offers only"
        )

    required = encoding[
        "required_fragments"
    ]

    valid_fragments = []

    for fragment_key, lease in sorted(
        leases.items(),
        key=lambda item: int(item[0]),
    ):
        if lease["status"] != "leased":
            continue

        fragment_index = int(
            fragment_key
        )

        fragment = get_manifest_fragment(
            manifest,
            fragment_index,
        )

        custodian_dir = find_peer_dir(
            lease["custodian"],
            peers_dir,
        )

        fragment_path = (
            custodian_dir
            / "data"
            / manifest["object_id"]
            / fragment["filename"]
        )

        if not fragment_path.exists():
            continue

        fragment_bytes = (
            fragment_path.read_bytes()
        )

        if len(fragment_bytes) != fragment["size"]:
            continue

        fragment_hash = (
            f"0x{keccak(fragment_bytes).hex()}"
        )

        if fragment_hash != fragment["hash"]:
            continue

        valid_fragments.append(
            (
                fragment["coefficient"],
                fragment_bytes,
            )
        )

        if len(valid_fragments) >= required:
            break

    if len(valid_fragments) < required:
        raise ValueError(
            f"Not enough valid custody fragments: "
            f"{len(valid_fragments)} available, "
            f"{required} required"
        )

    package = erasure_decode_2_of_5(
        valid_fragments,
        manifest["original_size"],
    )

    if len(package) != manifest["original_size"]:
        raise ValueError(
            "Reconstructed object size mismatch"
        )

    if get_object_id(package) != manifest["object_id"]:
        raise ValueError(
            "Reconstructed object hash mismatch"
        )

    if not verify_state_package(
        package
    ):
        raise ValueError(
            "Reconstructed state failed "
            "canonical verification"
        )

    return package


def reconstruct_from_network(
    object_id: str,
    peer_address: str,
    peers_dir: Path = DEFAULT_PEERS_DIR,
) -> bytes:
    peer_dir = find_peer_dir(
        peer_address,
        peers_dir,
    )

    object_dir = (
        peer_dir
        / "data"
        / object_id
    )

    manifest_path = (
        object_dir
        / "manifest.json"
    )

    custody_path = (
        object_dir
        / "custody.json"
    )

    if not manifest_path.exists():
        raise ValueError(
            "Starting peer manifest does not exist"
        )

    if not custody_path.exists():
        raise ValueError(
            "Starting peer custody view does not exist"
        )

    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )

    custody = json.loads(
        custody_path.read_text(
            encoding="utf-8"
        )
    )

    if manifest["object_id"] != object_id:
        raise ValueError(
            "Local manifest object ID mismatch"
        )

    encoding = manifest["encoding"]

    if encoding["type"] != "reed-solomon":
        raise ValueError(
            "Network reconstruction currently "
            "supports erasure-coded offers only"
        )

    required = encoding[
        "required_fragments"
    ]

    valid_fragments = []
    used_indices = set()
    now = utc_now()

    for fragment_key, lease in sorted(
        custody.items(),
        key=lambda item: int(item[0]),
    ):
        fragment_index = int(
            fragment_key
        )

        if fragment_index in used_indices:
            continue

        if lease["status"] != "leased":
            continue

        if parse_time(lease["expires_at"]) <= now:
            continue

        try:
            fragment = get_manifest_fragment(
                manifest,
                fragment_index,
            )

            custodian_dir = find_peer_dir(
                lease["custodian"],
                peers_dir,
            )
        except ValueError:
            continue

        fragment_path = (
            custodian_dir
            / "data"
            / object_id
            / fragment["filename"]
        )

        if not fragment_path.exists():
            continue

        fragment_bytes = (
            fragment_path.read_bytes()
        )

        if len(fragment_bytes) != fragment["size"]:
            continue

        fragment_hash = (
            f"0x{keccak(fragment_bytes).hex()}"
        )

        if fragment_hash != fragment["hash"]:
            continue

        used_indices.add(
            fragment_index
        )

        valid_fragments.append(
            (
                fragment["coefficient"],
                fragment_bytes,
            )
        )

        if len(valid_fragments) >= required:
            break

    if len(valid_fragments) < required:
        raise ValueError(
            f"Not enough valid network fragments: "
            f"{len(valid_fragments)} available, "
            f"{required} required"
        )

    package = erasure_decode_2_of_5(
        valid_fragments,
        manifest["original_size"],
    )

    if len(package) != manifest["original_size"]:
        raise ValueError(
            "Reconstructed object size mismatch"
        )

    if get_object_id(package) != object_id:
        raise ValueError(
            "Reconstructed object hash mismatch"
        )

    if not verify_state_package(
        package
    ):
        raise ValueError(
            "Reconstructed state failed "
            "canonical verification"
        )

    return package


def load_network_metadata(
    object_id: str,
    peer_address: str,
    peers_dir: Path = DEFAULT_PEERS_DIR,
) -> tuple[Path, dict, dict]:
    peer_dir = find_peer_dir(
        peer_address,
        peers_dir,
    )

    object_dir = (
        peer_dir
        / "data"
        / object_id
    )

    manifest_path = (
        object_dir
        / "manifest.json"
    )

    custody_path = (
        object_dir
        / "custody.json"
    )

    if not manifest_path.exists():
        raise ValueError(
            "Starting peer manifest does not exist"
        )

    if not custody_path.exists():
        raise ValueError(
            "Starting peer custody view does not exist"
        )

    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )

    custody = json.loads(
        custody_path.read_text(
            encoding="utf-8"
        )
    )

    if manifest["object_id"] != object_id:
        raise ValueError(
            "Local manifest object ID mismatch"
        )

    return object_dir, manifest, custody


def get_valid_active_fragments(
    object_id: str,
    manifest: dict,
    custody: dict,
    peers_dir: Path = DEFAULT_PEERS_DIR,
    now: datetime | None = None,
) -> list[tuple[int, dict, dict, bytes]]:
    if now is None:
        now = utc_now()

    valid = []
    used_indices = set()

    for fragment_key, lease in sorted(
        custody.items(),
        key=lambda item: int(item[0]),
    ):
        fragment_index = int(
            fragment_key
        )

        if fragment_index in used_indices:
            continue

        if lease["status"] != "leased":
            continue

        if parse_time(lease["expires_at"]) <= now:
            continue

        try:
            fragment = get_manifest_fragment(
                manifest,
                fragment_index,
            )

            custodian_dir = find_peer_dir(
                lease["custodian"],
                peers_dir,
            )
        except ValueError:
            continue

        fragment_path = (
            custodian_dir
            / "data"
            / object_id
            / fragment["filename"]
        )

        if not fragment_path.exists():
            continue

        fragment_bytes = (
            fragment_path.read_bytes()
        )

        if len(fragment_bytes) != fragment["size"]:
            continue

        fragment_hash = (
            f"0x{keccak(fragment_bytes).hex()}"
        )

        if fragment_hash != fragment["hash"]:
            continue

        used_indices.add(
            fragment_index
        )

        valid.append(
            (
                fragment_index,
                lease,
                fragment,
                fragment_bytes,
            )
        )

    return valid


def replicate_network_custody(
    object_id: str,
    custody: dict,
    peers_dir: Path = DEFAULT_PEERS_DIR,
    additional_peers: tuple[str, ...] = (),
) -> None:
    now = utc_now()

    addresses = {
        lease["custodian"]
        for lease in custody.values()
        if (
            lease["status"] == "leased"
            and parse_time(
                lease["expires_at"]
            ) > now
        )
    }

    addresses.update(
        additional_peers
    )

    content = (
        json.dumps(
            custody,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    for address in sorted(
        addresses,
        key=str.lower,
    ):
        try:
            custodian_dir = find_peer_dir(
                address,
                peers_dir,
            )
        except ValueError:
            continue

        custody_path = (
            custodian_dir
            / "data"
            / object_id
            / "custody.json"
        )

        if custody_path.parent.exists():
            custody_path.write_text(
                content,
                encoding="utf-8",
            )


def renew_custody(
    object_id: str,
    peer_address: str,
    peers_dir: Path = DEFAULT_PEERS_DIR,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict:
    object_dir, manifest, custody = (
        load_network_metadata(
            object_id,
            peer_address,
            peers_dir,
        )
    )

    now = utc_now()
    matching = [
        (fragment_key, lease)
        for fragment_key, lease
        in custody.items()
        if (
            lease["custodian"].lower()
            == peer_address.lower()
        )
    ]

    if len(matching) != 1:
        raise ValueError(
            "Peer must have exactly one custody claim"
        )

    fragment_key, lease = matching[0]

    if (
        lease["status"] != "leased"
        or parse_time(lease["expires_at"]) <= now
    ):
        raise ValueError(
            "Custody claim is not active"
        )

    fragment = get_manifest_fragment(
        manifest,
        int(fragment_key),
    )

    fragment_path = (
        object_dir
        / fragment["filename"]
    )

    if not fragment_path.exists():
        raise ValueError(
            "Custodian fragment is missing"
        )

    fragment_bytes = fragment_path.read_bytes()

    if (
        len(fragment_bytes) != fragment["size"]
        or f"0x{keccak(fragment_bytes).hex()}"
        != fragment["hash"]
    ):
        raise ValueError(
            "Custodian fragment is invalid"
        )

    expires_at = (
        parse_time(lease["expires_at"])
        + timedelta(seconds=lease_seconds)
    )

    lease["expires_at"] = format_time(
        expires_at
    )

    receipt_path = (
        object_dir
        / "lease.json"
    )

    receipt = json.loads(
        receipt_path.read_text(
            encoding="utf-8"
        )
    )

    receipt["expires_at"] = (
        lease["expires_at"]
    )

    receipt_path.write_text(
        json.dumps(
            receipt,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    replicate_network_custody(
        object_id,
        custody,
        peers_dir,
    )

    return {
        "fragment_index": int(fragment_key),
        "custodian": peer_address,
        "expires_at": lease["expires_at"],
    }


def repair_network(
    object_id: str,
    peer_address: str,
    new_custodian_address: str,
    peers_dir: Path = DEFAULT_PEERS_DIR,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict:
    object_dir, manifest, custody = (
        load_network_metadata(
            object_id,
            peer_address,
            peers_dir,
        )
    )

    if manifest["encoding"]["type"] != "reed-solomon":
        raise ValueError(
            "Network repair supports "
            "erasure-coded offers only"
        )

    valid = get_valid_active_fragments(
        object_id,
        manifest,
        custody,
        peers_dir,
    )

    active_addresses = {
        lease["custodian"]
        for _, lease, _, _ in valid
    }

    if not active_addresses:
        raise ValueError(
            "No active custodians available"
        )

    executor = min(
        active_addresses,
        key=str.lower,
    )

    if peer_address.lower() != executor.lower():
        raise ValueError(
            f"Repair executor is {executor}"
        )

    active_indices = {
        fragment_index
        for fragment_index, _, _, _ in valid
    }

    missing_indices = [
        fragment["index"]
        for fragment in sorted(
            manifest["fragments"],
            key=lambda item: item["index"],
        )
        if fragment["index"] not in active_indices
    ]

    if not missing_indices:
        raise ValueError(
            "No missing or expired fragments"
        )

    required = manifest[
        "encoding"
    ]["required_fragments"]

    if len(valid) < required:
        raise ValueError(
            f"Not enough valid active fragments: "
            f"{len(valid)} available, "
            f"{required} required"
        )

    now = utc_now()

    if any(
        (
            lease["custodian"].lower()
            == new_custodian_address.lower()
            and lease["status"] == "leased"
            and parse_time(lease["expires_at"])
            > now
        )
        for lease in custody.values()
    ):
        raise ValueError(
            "New custodian already has a claim "
            "for this object"
        )

    new_custodian_dir = find_peer_dir(
        new_custodian_address,
        peers_dir,
    )

    fragment_index = missing_indices[0]
    fragment = get_manifest_fragment(
        manifest,
        fragment_index,
    )

    if not can_accept(
        new_custodian_dir,
        fragment["size"],
    ):
        raise ValueError(
            "New custodian does not have "
            "enough capacity"
        )

    recovery_fragments = [
        (
            item["coefficient"],
            fragment_bytes,
        )
        for _, _, item, fragment_bytes
        in valid[:required]
    ]

    package = erasure_decode_2_of_5(
        recovery_fragments,
        manifest["original_size"],
    )

    if get_object_id(package) != object_id:
        raise ValueError(
            "Reconstructed object hash mismatch"
        )

    if not verify_state_package(package):
        raise ValueError(
            "Reconstructed state failed "
            "canonical verification"
        )

    regenerated = erasure_encode_2_of_5(
        package
    )[fragment_index][1]

    if (
        len(regenerated) != fragment["size"]
        or f"0x{keccak(regenerated).hex()}"
        != fragment["hash"]
    ):
        raise ValueError(
            "Regenerated fragment does not "
            "match the manifest"
        )

    destination_dir = (
        new_custodian_dir
        / "data"
        / object_id
    )

    destination_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination_path = (
        destination_dir
        / fragment["filename"]
    )

    destination_path.write_bytes(
        regenerated
    )

    shutil.copyfile(
        object_dir / "manifest.json",
        destination_dir / "manifest.json",
    )

    now = utc_now()
    expires_at = now + timedelta(
        seconds=lease_seconds
    )

    lease_record = {
        "custodian": new_custodian_dir.name,
        "status": "leased",
        "started_at": format_time(now),
        "expires_at": format_time(expires_at),
    }

    custody[str(fragment_index)] = (
        lease_record
    )

    write_local_lease_receipt(
        custodian_dir=new_custodian_dir,
        object_id=object_id,
        publisher_address=manifest["address"],
        fragment_index=fragment_index,
        started_at=lease_record["started_at"],
        expires_at=lease_record["expires_at"],
    )

    replicate_network_custody(
        object_id,
        custody,
        peers_dir,
        additional_peers=(
            new_custodian_dir.name,
        ),
    )

    return {
        "executor": executor,
        "fragment_index": fragment_index,
        "custodian": new_custodian_dir.name,
        "destination": str(destination_path),
        "expires_at": lease_record["expires_at"],
    }
