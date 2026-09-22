import json
import shutil

from pathlib import Path

from eth_utils import keccak, to_checksum_address
from modules.canonical_history import (
    canonical_source,
    commit_at_height,
    current_commit,
    register_object,
)

from modules.merkle import (
    find_peer_dir,
    get_self_cache,
    load_peer_proof,
    load_state_root,
    verify_peer,
)


DEFAULT_PEERS_DIR = Path("data/peers")
DEFAULT_REFERENCE_DIR = Path("data/reference")

MAGIC = b"SFSP"
VERSION = 1

ADDRESS_SIZE = 20
ROOT_SIZE = 32
BALANCE_SIZE = 32
NONCE_SIZE = 8
PROOF_COUNT_SIZE = 2
PROOF_ENTRY_SIZE = 33

SIDE_LEFT = 0
SIDE_RIGHT = 1


def address_to_bytes(address: str) -> bytes:
    value = address.removeprefix("0x")

    raw = bytes.fromhex(value)

    if len(raw) != ADDRESS_SIZE:
        raise ValueError(
            "Ethereum address must be 20 bytes"
        )

    return raw


def proof_to_bytes(
    proof: list[dict[str, str]],
) -> bytes:
    encoded = bytearray()

    for item in proof:
        side = item["side"]

        if side == "left":
            encoded.append(SIDE_LEFT)
        elif side == "right":
            encoded.append(SIDE_RIGHT)
        else:
            raise ValueError(
                f"Invalid proof side: {side}"
            )

        sibling_hex = item["hash"].removeprefix("0x")
        sibling_hash = bytes.fromhex(sibling_hex)

        if len(sibling_hash) != 32:
            raise ValueError(
                "Merkle proof hash must be 32 bytes"
            )

        encoded.extend(sibling_hash)

    return bytes(encoded)


def build_state_package(
    address: str,
    peers_dir: Path = DEFAULT_PEERS_DIR,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> bytes:
    if not verify_peer(
        address,
        peers_dir=peers_dir,
        reference_dir=reference_dir,
    ):
        raise ValueError(
            f"Peer state failed verification: {address}"
        )

    peer_dir = find_peer_dir(
        address,
        peers_dir,
    )

    self_cache = get_self_cache(
        peer_dir
    )

    balance = int(
        (self_cache / "balance")
        .read_text(encoding="utf-8")
        .strip()
    )

    nonce = int(
        (self_cache / "nonce")
        .read_text(encoding="utf-8")
        .strip()
    )

    state_root = load_state_root(
        reference_dir
    )

    proof = load_peer_proof(
        peer_dir
    )

    address_bytes = address_to_bytes(
        peer_dir.name
    )

    balance_bytes = balance.to_bytes(
        BALANCE_SIZE,
        byteorder="big",
        signed=False,
    )

    nonce_bytes = nonce.to_bytes(
        NONCE_SIZE,
        byteorder="big",
        signed=False,
    )

    proof_count = len(proof)

    if proof_count > 65535:
        raise ValueError(
            "Merkle proof is too large"
        )

    proof_count_bytes = proof_count.to_bytes(
        PROOF_COUNT_SIZE,
        byteorder="big",
        signed=False,
    )

    proof_bytes = proof_to_bytes(
        proof
    )

    package = (
        MAGIC
        + VERSION.to_bytes(1, byteorder="big")
        + state_root
        + address_bytes
        + balance_bytes
        + nonce_bytes
        + proof_count_bytes
        + proof_bytes
    )

    return package


def get_object_id(
    package: bytes,
) -> str:
    return f"0x{keccak(package).hex()}"


def parse_state_package(
    package: bytes,
) -> dict:
    minimum_size = (
        len(MAGIC)
        + 1
        + ROOT_SIZE
        + ADDRESS_SIZE
        + BALANCE_SIZE
        + NONCE_SIZE
        + PROOF_COUNT_SIZE
    )

    if len(package) < minimum_size:
        raise ValueError(
            "State package is too small"
        )

    offset = 0

    magic = package[
        offset:offset + len(MAGIC)
    ]
    offset += len(MAGIC)

    if magic != MAGIC:
        raise ValueError(
            "Invalid state package magic"
        )

    version = package[offset]
    offset += 1

    if version != VERSION:
        raise ValueError(
            f"Unsupported state package version: {version}"
        )

    state_root = package[
        offset:offset + ROOT_SIZE
    ]
    offset += ROOT_SIZE

    address_bytes = package[
        offset:offset + ADDRESS_SIZE
    ]
    offset += ADDRESS_SIZE

    balance_bytes = package[
        offset:offset + BALANCE_SIZE
    ]
    offset += BALANCE_SIZE

    nonce_bytes = package[
        offset:offset + NONCE_SIZE
    ]
    offset += NONCE_SIZE

    proof_count = int.from_bytes(
        package[
            offset:offset + PROOF_COUNT_SIZE
        ],
        byteorder="big",
    )
    offset += PROOF_COUNT_SIZE

    expected_size = (
        minimum_size
        + proof_count * PROOF_ENTRY_SIZE
    )

    if len(package) != expected_size:
        raise ValueError(
            "State package size does not match proof count"
        )

    proof = []

    for _ in range(proof_count):
        side_value = package[offset]
        offset += 1

        sibling_hash = package[
            offset:offset + 32
        ]
        offset += 32

        if side_value == SIDE_LEFT:
            side = "left"
        elif side_value == SIDE_RIGHT:
            side = "right"
        else:
            raise ValueError(
                f"Invalid proof side byte: {side_value}"
            )

        proof.append(
            {
                "side": side,
                "hash": (
                    f"0x{sibling_hash.hex()}"
                ),
            }
        )

    address = to_checksum_address(
        address_bytes
    )

    balance = int.from_bytes(
        balance_bytes,
        byteorder="big",
    )

    nonce = int.from_bytes(
        nonce_bytes,
        byteorder="big",
    )

    return {
        "version": version,
        "state_root": f"0x{state_root.hex()}",
        "address": address,
        "balance": balance,
        "nonce": nonce,
        "proof": proof,
    }


#
# Fragment encoding
#

GF_POLY = 0x11D

ERASURE_DATA_FRAGMENTS = 2
ERASURE_RECOVERY_FRAGMENTS = 3
ERASURE_TOTAL_FRAGMENTS = 5


def gf_mul(a: int, b: int) -> int:
    result = 0

    while b:
        if b & 1:
            result ^= a

        b >>= 1
        a <<= 1

        if a & 0x100:
            a ^= GF_POLY

    return result & 0xFF


def gf_pow(value: int, power: int) -> int:
    result = 1

    while power:
        if power & 1:
            result = gf_mul(
                result,
                value,
            )

        value = gf_mul(
            value,
            value,
        )

        power >>= 1

    return result


def gf_inv(value: int) -> int:
    if value == 0:
        raise ZeroDivisionError(
            "Cannot invert zero in GF(256)"
        )

    return gf_pow(
        value,
        254,
    )


def gf_div(a: int, b: int) -> int:
    return gf_mul(
        a,
        gf_inv(b),
    )


#
# Plain RAID-0-style striping
#

def stripe_bytes(
    data: bytes,
    fragment_count: int = 4,
) -> list[bytes]:
    if fragment_count < 1:
        raise ValueError(
            "Fragment count must be at least 1"
        )

    if fragment_count > len(data):
        raise ValueError(
            "Fragment count cannot exceed object size"
        )

    fragment_size = (
        len(data)
        + fragment_count
        - 1
    ) // fragment_count

    fragments = []

    for offset in range(
        0,
        len(data),
        fragment_size,
    ):
        fragments.append(
            data[
                offset:
                offset + fragment_size
            ]
        )

    return fragments


#
# Reed-Solomon RS(5,2)
#

def erasure_encode_2_of_5(
    data: bytes,
) -> list[tuple[int, bytes]]:
    shard_size = (
        len(data) + 1
    ) // 2

    padded = data.ljust(
        shard_size * 2,
        b"\x00",
    )

    data_a = padded[
        :shard_size
    ]

    data_b = padded[
        shard_size:
    ]

    fragments = []

    for coefficient in range(
        1,
        ERASURE_TOTAL_FRAGMENTS + 1,
    ):
        encoded = bytearray(
            shard_size
        )

        for index in range(
            shard_size
        ):
            encoded[index] = (
                data_a[index]
                ^ gf_mul(
                    coefficient,
                    data_b[index],
                )
            )

        fragments.append(
            (
                coefficient,
                bytes(encoded),
            )
        )

    return fragments


def erasure_decode_2_of_5(
    fragments: list[tuple[int, bytes]],
    original_size: int,
) -> bytes:
    if len(fragments) < 2:
        raise ValueError(
            "At least 2 valid fragments are required"
        )

    x1, shard_1 = fragments[0]
    x2, shard_2 = fragments[1]

    if x1 == x2:
        raise ValueError(
            "Fragments must use different coefficients"
        )

    if len(shard_1) != len(shard_2):
        raise ValueError(
            "Fragment sizes do not match"
        )

    shard_size = len(
        shard_1
    )

    data_a = bytearray(
        shard_size
    )

    data_b = bytearray(
        shard_size
    )

    denominator = (
        x1 ^ x2
    )

    for index in range(
        shard_size
    ):
        y1 = shard_1[index]
        y2 = shard_2[index]

        b = gf_div(
            y1 ^ y2,
            denominator,
        )

        a = (
            y1
            ^ gf_mul(
                x1,
                b,
            )
        )

        data_a[index] = a
        data_b[index] = b

    reconstructed = (
        bytes(data_a)
        + bytes(data_b)
    )

    return reconstructed[
        :original_size
    ]


#
# State-package verification
#

def verify_state_package(
    package: bytes,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
    canonical_height: int | None = None,
    expected_root: bytes | None = None,
) -> bool:
    parsed = parse_state_package(
        package
    )

    trusted_root = (
        expected_root if expected_root is not None else
        bytes.fromhex(commit_at_height(canonical_height, reference_dir)["state_root"][2:])
        if canonical_height is not None else load_state_root(reference_dir)
    )

    package_root = bytes.fromhex(
        parsed["state_root"]
        .removeprefix("0x")
    )

    if package_root != trusted_root:
        return False

    canonical = (
        f"address={parsed['address'].lower()}\n"
        f"balance={parsed['balance']}\n"
        f"nonce={parsed['nonce']}\n"
    ).encode("utf-8")

    current_hash = keccak(
        canonical
    )

    for item in parsed["proof"]:
        sibling_hash = bytes.fromhex(
            item["hash"]
            .removeprefix("0x")
        )

        if item["side"] == "left":
            current_hash = keccak(
                sibling_hash
                + current_hash
            )

        elif item["side"] == "right":
            current_hash = keccak(
                current_hash
                + sibling_hash
            )

        else:
            return False

    return (
        current_hash
        == trusted_root
    )


def verify_package_for_manifest(
    package: bytes,
    manifest: dict,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
    expected_height: int | None = None,
) -> bool:
    """Verify bytes against the manifest's immutable canonical reference."""
    try:
        root = canonical_source(reference_dir).root_for_manifest(
            manifest, expected_sequence=expected_height,
        )
    except ValueError:
        return False
    return (
        manifest["object_id"] == get_object_id(package)
        and verify_state_package(
            package,
            reference_dir=reference_dir,
            expected_root=bytes.fromhex(root[2:]),
        )
    )


#
# Offer creation
#

def create_offer(
    address: str,
    encoding_type: str = "erasure",
    fragment_count: int = 4,
    peers_dir: Path = DEFAULT_PEERS_DIR,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> dict:
    package = build_state_package(
        address,
        peers_dir=peers_dir,
        reference_dir=reference_dir,
    )

    parsed = parse_state_package(
        package
    )

    object_id = get_object_id(
        package
    )

    canonical = current_commit(reference_dir)
    if canonical["state_root"] != parsed["state_root"]:
        raise ValueError("Offer root does not match current canonical commit")

    peer_dir = find_peer_dir(
        address,
        peers_dir,
    )

    offer_dir = (
        peer_dir
        / "offers"
        / object_id
    )

    fragments_dir = (
        offer_dir
        / "fragments"
    )

    if offer_dir.exists():
        shutil.rmtree(
            offer_dir
        )

    fragments_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    fragment_manifest = []

    if encoding_type == "stripe":
        fragments = stripe_bytes(
            package,
            fragment_count,
        )

        for index, fragment in enumerate(
            fragments
        ):
            filename = (
                f"{index:03d}.bin"
            )

            (
                fragments_dir
                / filename
            ).write_bytes(
                fragment
            )

            fragment_manifest.append(
                {
                    "index": index,
                    "filename": filename,
                    "size": len(fragment),
                    "hash": (
                        f"0x{keccak(fragment).hex()}"
                    ),
                }
            )

        encoding = {
            "type": "stripe",
            "data_fragments": len(fragments),
            "recovery_fragments": 0,
            "required_fragments": len(fragments),
            "total_fragments": len(fragments),
        }

    elif encoding_type == "erasure":
        encoded_fragments = (
            erasure_encode_2_of_5(
                package
            )
        )

        for index, (
            coefficient,
            fragment,
        ) in enumerate(
            encoded_fragments
        ):
            filename = (
                f"{index:03d}.bin"
            )

            (
                fragments_dir
                / filename
            ).write_bytes(
                fragment
            )

            fragment_manifest.append(
                {
                    "index": index,
                    "coefficient": coefficient,
                    "filename": filename,
                    "size": len(fragment),
                    "hash": (
                        f"0x{keccak(fragment).hex()}"
                    ),
                }
            )

        encoding = {
            "type": "reed-solomon",
            "field": "gf256",
            "data_fragments": 2,
            "recovery_fragments": 3,
            "required_fragments": 2,
            "total_fragments": 5,
        }

    else:
        raise ValueError(
            f"Unsupported encoding type: "
            f"{encoding_type}"
        )

    manifest = {
        "manifest_version": 1,
        "object_type": "state-package",
        "object_id": object_id,
        "address": parsed["address"],
        "state_root": parsed["state_root"],
        "canonical_height": canonical["height"],
        "original_size": len(package),
        "hash_algorithm": "keccak256",
        "encoding": encoding,
        "fragments": fragment_manifest,
    }

    (
        offer_dir
        / "manifest.json"
    ).write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    register_object(peer_dir.name, parsed["state_root"], object_id, reference_dir)

    return manifest


def load_manifest(
    offer_dir: Path,
) -> dict:
    manifest_path = (
        offer_dir
        / "manifest.json"
    )

    if not manifest_path.exists():
        raise ValueError(
            "Offer manifest does not exist"
        )

    return json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )


def load_valid_fragments(
    offer_dir: Path,
    manifest: dict,
) -> list[tuple[dict, bytes]]:
    fragments_dir = (
        offer_dir
        / "fragments"
    )

    valid = []

    for item in sorted(
        manifest["fragments"],
        key=lambda entry: entry["index"],
    ):
        fragment_path = (
            fragments_dir
            / item["filename"]
        )

        if not fragment_path.exists():
            continue

        fragment = (
            fragment_path.read_bytes()
        )

        if len(fragment) != item["size"]:
            continue

        fragment_hash = (
            f"0x{keccak(fragment).hex()}"
        )

        if fragment_hash != item["hash"]:
            continue

        valid.append(
            (
                item,
                fragment,
            )
        )

    return valid


#
# Reconstruction
#

def reconstruct_offer(
    offer_dir: Path,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> bytes:
    manifest = load_manifest(
        offer_dir
    )

    encoding = (
        manifest["encoding"]
    )

    valid_fragments = (
        load_valid_fragments(
            offer_dir,
            manifest,
        )
    )

    required = (
        encoding[
            "required_fragments"
        ]
    )

    if len(valid_fragments) < required:
        raise ValueError(
            f"Not enough valid fragments: "
            f"{len(valid_fragments)} available, "
            f"{required} required"
        )

    if encoding["type"] == "stripe":
        fragment_map = {
            item["index"]: fragment
            for item, fragment
            in valid_fragments
        }

        ordered = []

        for item in sorted(
            manifest["fragments"],
            key=lambda entry: entry["index"],
        ):
            index = item["index"]

            if index not in fragment_map:
                raise ValueError(
                    f"Missing fragment: "
                    f"{item['filename']}"
                )

            ordered.append(
                fragment_map[index]
            )

        package = b"".join(
            ordered
        )

    elif encoding["type"] == "reed-solomon":
        recovery_fragments = [
            (
                item["coefficient"],
                fragment,
            )
            for item, fragment
            in valid_fragments
        ]

        package = (
            erasure_decode_2_of_5(
                recovery_fragments,
                manifest["original_size"],
            )
        )

    else:
        raise ValueError(
            "Unsupported encoding type"
        )

    package = package[
        :manifest["original_size"]
    ]

    if len(package) != manifest["original_size"]:
        raise ValueError(
            "Reconstructed object size mismatch"
        )

    if get_object_id(package) != manifest["object_id"]:
        raise ValueError(
            "Reconstructed object hash mismatch"
        )

    if not verify_state_package(
        package,
        reference_dir=reference_dir,
    ):
        raise ValueError(
            "Reconstructed state failed "
            "canonical verification"
        )

    return package
