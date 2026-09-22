from pathlib import Path
import json

from eth_utils import keccak
from modules.canonical_history import record_commit


DEFAULT_PEERS_DIR = Path("data/peers")
DEFAULT_REFERENCE_DIR = Path("data/reference")


def get_self_cache(peer_dir: Path) -> Path:
    return peer_dir / "cache" / "self"


def load_peer_dirs(
    peers_dir: Path = DEFAULT_PEERS_DIR,
) -> list[Path]:
    if not peers_dir.exists():
        raise ValueError(
            f"Peers directory does not exist: {peers_dir}"
        )

    peer_dirs = sorted(
        (
            path
            for path in peers_dir.iterdir()
            if path.is_dir()
        ),
        key=lambda path: path.name.lower(),
    )

    if not peer_dirs:
        raise ValueError("No peers found")

    return peer_dirs


def serialize_peer_state(peer_dir: Path) -> bytes:
    address = peer_dir.name
    self_cache = get_self_cache(peer_dir)

    balance_path = self_cache / "balance"
    nonce_path = self_cache / "nonce"

    if not balance_path.exists():
        raise ValueError(
            f"Missing balance for peer: {address}"
        )

    if not nonce_path.exists():
        raise ValueError(
            f"Missing nonce for peer: {address}"
        )

    balance = int(
        balance_path.read_text(
            encoding="utf-8"
        ).strip()
    )

    nonce = int(
        nonce_path.read_text(
            encoding="utf-8"
        ).strip()
    )

    canonical = (
        f"address={address.lower()}\n"
        f"balance={balance}\n"
        f"nonce={nonce}\n"
    )

    return canonical.encode("utf-8")


def hash_peer_state(peer_dir: Path) -> bytes:
    state_bytes = serialize_peer_state(
        peer_dir
    )

    return keccak(state_bytes)


def load_leaf_hashes(
    peers_dir: Path = DEFAULT_PEERS_DIR,
) -> list[bytes]:
    peer_dirs = load_peer_dirs(
        peers_dir
    )

    return [
        hash_peer_state(peer_dir)
        for peer_dir in peer_dirs
    ]


def build_merkle_levels(
    leaves: list[bytes],
) -> list[list[bytes]]:
    if not leaves:
        raise ValueError(
            "Cannot build tree without leaves"
        )

    levels = [
        list(leaves)
    ]

    current_level = list(leaves)

    while len(current_level) > 1:
        working_level = list(
            current_level
        )

        if len(working_level) % 2 != 0:
            working_level.append(
                working_level[-1]
            )

        next_level = []

        for index in range(
            0,
            len(working_level),
            2,
        ):
            left = working_level[index]
            right = working_level[index + 1]

            parent = keccak(
                left + right
            )

            next_level.append(
                parent
            )

        levels.append(
            next_level
        )

        current_level = next_level

    return levels


def build_merkle_root(
    leaves: list[bytes],
) -> bytes:
    levels = build_merkle_levels(
        leaves
    )

    return levels[-1][0]


def build_proof(
    levels: list[list[bytes]],
    leaf_index: int,
) -> list[dict[str, str]]:
    if not levels:
        raise ValueError(
            "Merkle tree has no levels"
        )

    if leaf_index < 0:
        raise ValueError(
            "Leaf index cannot be negative"
        )

    if leaf_index >= len(levels[0]):
        raise ValueError(
            "Leaf index is outside the tree"
        )

    proof = []
    index = leaf_index

    for level in levels[:-1]:
        working_level = list(level)

        if len(working_level) % 2 != 0:
            working_level.append(
                working_level[-1]
            )

        if index % 2 == 0:
            sibling_index = index + 1
            side = "right"
        else:
            sibling_index = index - 1
            side = "left"

        sibling_hash = (
            working_level[sibling_index]
        )

        proof.append(
            {
                "side": side,
                "hash": (
                    f"0x{sibling_hash.hex()}"
                ),
            }
        )

        index //= 2

    return proof


def write_peer_proof(
    peer_dir: Path,
    proof: list[dict[str, str]],
) -> None:
    self_cache = get_self_cache(
        peer_dir
    )

    proof_data = {
        "address": peer_dir.name,
        "proof": proof,
    }

    proof_path = (
        self_cache / "proof.json"
    )

    proof_path.write_text(
        json.dumps(
            proof_data,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def commit_state(
    peers_dir: Path = DEFAULT_PEERS_DIR,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> bytes:
    peer_dirs = load_peer_dirs(
        peers_dir
    )

    leaves = [
        hash_peer_state(peer_dir)
        for peer_dir in peer_dirs
    ]

    levels = build_merkle_levels(
        leaves
    )

    root = levels[-1][0]

    reference_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    root_hex = (
        f"0x{root.hex()}"
    )

    (
        reference_dir / "state_root"
    ).write_text(
        f"{root_hex}\n",
        encoding="utf-8",
    )

    for index, peer_dir in enumerate(
        peer_dirs
    ):
        proof = build_proof(
            levels,
            index,
        )

        write_peer_proof(
            peer_dir,
            proof,
        )

    record_commit(root_hex, reference_dir)

    return root


def load_state_root(
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> bytes:
    root_path = (
        reference_dir / "state_root"
    )

    if not root_path.exists():
        raise ValueError(
            "State root does not exist. "
            "Run commit first."
        )

    root_hex = root_path.read_text(
        encoding="utf-8"
    ).strip()

    if root_hex.startswith("0x"):
        root_hex = root_hex[2:]

    root = bytes.fromhex(
        root_hex
    )

    if len(root) != 32:
        raise ValueError(
            "State root must be 32 bytes"
        )

    return root


def find_peer_dir(
    address: str,
    peers_dir: Path = DEFAULT_PEERS_DIR,
) -> Path:
    peer_dirs = load_peer_dirs(
        peers_dir
    )

    for peer_dir in peer_dirs:
        if (
            peer_dir.name.lower()
            == address.lower()
        ):
            return peer_dir

    raise ValueError(
        f"Peer not found: {address}"
    )


def load_peer_proof(
    peer_dir: Path,
) -> list[dict[str, str]]:
    proof_path = (
        get_self_cache(peer_dir)
        / "proof.json"
    )

    if not proof_path.exists():
        raise ValueError(
            f"Proof does not exist for "
            f"{peer_dir.name}. "
            "Run commit first."
        )

    proof_data = json.loads(
        proof_path.read_text(
            encoding="utf-8"
        )
    )

    proof_address = proof_data.get(
        "address"
    )

    if (
        proof_address is None
        or proof_address.lower()
        != peer_dir.name.lower()
    ):
        raise ValueError(
            "Proof address does not "
            "match peer address"
        )

    return proof_data["proof"]


def verify_proof(
    peer_dir: Path,
    proof: list[dict[str, str]],
    expected_root: bytes,
) -> bool:
    current_hash = hash_peer_state(
        peer_dir
    )

    for proof_item in proof:
        side = proof_item["side"]
        sibling_hex = (
            proof_item["hash"]
        )

        if sibling_hex.startswith("0x"):
            sibling_hex = sibling_hex[2:]

        sibling_hash = bytes.fromhex(
            sibling_hex
        )

        if len(sibling_hash) != 32:
            raise ValueError(
                "Merkle proof hash "
                "must be 32 bytes"
            )

        if side == "left":
            current_hash = keccak(
                sibling_hash
                + current_hash
            )

        elif side == "right":
            current_hash = keccak(
                current_hash
                + sibling_hash
            )

        else:
            raise ValueError(
                f"Invalid proof side: {side}"
            )

    return (
        current_hash
        == expected_root
    )


def verify_peer(
    address: str,
    peers_dir: Path = DEFAULT_PEERS_DIR,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> bool:
    peer_dir = find_peer_dir(
        address,
        peers_dir,
    )

    proof = load_peer_proof(
        peer_dir
    )

    state_root = load_state_root(
        reference_dir
    )

    return verify_proof(
        peer_dir,
        proof,
        state_root,
    )
