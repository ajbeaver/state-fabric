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

        (self_cache / "balance").write_text(
            f"{balance}\n",
            encoding="utf-8",
        )

        (self_cache / "nonce").write_text(
            f"{nonce}\n",
            encoding="utf-8",
        )

    return len(wallets)
