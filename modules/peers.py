from pathlib import Path
import shutil

from eth_utils import keccak

from modules.wallets import generate_wallets


DEFAULT_PEERS_DIR = Path("data/peers")
DEFAULT_REFERENCE_DIR = Path("data/reference")
DEFAULT_SEED = "state-fabric-v1"

WEI_PER_ETH = 10**18
MAX_BALANCE_ETH = 100
MAX_NONCE = 20

KIB = 1024
MIB = 1024 * KIB
GIB = 1024 * MIB

CAPACITY_LEVELS = (
    64 * KIB,
    64 * MIB,
    1 * GIB,
)


def derive_balance(seed: str, index: int) -> int:
    material = f"{seed}:balance:{index}".encode("utf-8")
    digest = keccak(material)

    return int.from_bytes(
        digest,
        byteorder="big",
    ) % (MAX_BALANCE_ETH * WEI_PER_ETH)


def derive_nonce(seed: str, index: int) -> int:
    material = f"{seed}:nonce:{index}".encode("utf-8")
    digest = keccak(material)

    return int.from_bytes(
        digest,
        byteorder="big",
    ) % (MAX_NONCE + 1)


def derive_capacity(seed: str, index: int) -> int:
    material = f"{seed}:capacity:{index}".encode("utf-8")
    digest = keccak(material)

    capacity_index = (
        int.from_bytes(
            digest,
            byteorder="big",
        )
        % len(CAPACITY_LEVELS)
    )

    return CAPACITY_LEVELS[capacity_index]


def get_capacity(peer_dir: Path) -> int:
    capacity_path = peer_dir / "capacity"

    if not capacity_path.exists():
        raise ValueError(
            f"Capacity not found for peer: {peer_dir.name}"
        )

    return int(
        capacity_path.read_text(
            encoding="utf-8"
        ).strip()
    )


def get_used_capacity(peer_dir: Path) -> int:
    data_dir = peer_dir / "data"

    if not data_dir.exists():
        return 0

    return sum(
        path.stat().st_size
        for path in data_dir.rglob("*")
        if path.is_file()
    )


def get_available_capacity(peer_dir: Path) -> int:
    capacity = get_capacity(peer_dir)
    used = get_used_capacity(peer_dir)

    return max(
        capacity - used,
        0,
    )


def can_accept(
    peer_dir: Path,
    size: int,
) -> bool:
    if size < 0:
        raise ValueError(
            "Fragment size cannot be negative"
        )

    return size <= get_available_capacity(
        peer_dir
    )


def initialize_peers(
    count: int,
    seed: str = DEFAULT_SEED,
    peers_dir: Path = DEFAULT_PEERS_DIR,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> int:
    if count < 1:
        raise ValueError(
            "Peer count must be at least 1"
        )

    if peers_dir.exists():
        shutil.rmtree(peers_dir)

    if reference_dir.exists():
        shutil.rmtree(reference_dir)

    peers_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    wallets = generate_wallets(
        count,
        seed,
    )

    for index, wallet in enumerate(wallets):
        peer_dir = peers_dir / wallet.address
        self_cache = peer_dir / "cache" / "self"
        data_dir = peer_dir / "data"

        self_cache.mkdir(
            parents=True,
            exist_ok=True,
        )

        data_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        balance = derive_balance(
            seed,
            index,
        )

        nonce = derive_nonce(
            seed,
            index,
        )

        capacity = derive_capacity(
            seed,
            index,
        )

        (peer_dir / "capacity").write_text(
            f"{capacity}\n",
            encoding="utf-8",
        )

        (self_cache / "balance").write_text(
            f"{balance}\n",
            encoding="utf-8",
        )

        (self_cache / "nonce").write_text(
            f"{nonce}\n",
            encoding="utf-8",
        )

    return len(wallets)
