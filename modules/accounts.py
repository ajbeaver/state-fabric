from pathlib import Path
import shutil

from eth_utils import keccak

from modules.wallets import generate_wallets


DEFAULT_DATA_DIR = Path("data/accounts")
DEFAULT_SEED = "state-fabric-v1"

WEI_PER_ETH = 10**18
MAX_BALANCE_ETH = 100
MAX_NONCE = 20


def derive_balance(seed: str, index: int) -> int:
    material = f"{seed}:balance:{index}".encode("utf-8")
    digest = keccak(material)

    return int.from_bytes(digest, byteorder="big") % (
        MAX_BALANCE_ETH * WEI_PER_ETH
    )


def derive_nonce(seed: str, index: int) -> int:
    material = f"{seed}:nonce:{index}".encode("utf-8")
    digest = keccak(material)

    return int.from_bytes(digest, byteorder="big") % (MAX_NONCE + 1)


def initialize_accounts(
    count: int,
    seed: str = DEFAULT_SEED,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> None:
    if data_dir.exists():
        shutil.rmtree(data_dir)

    data_dir.mkdir(parents=True)

    wallets = generate_wallets(count, seed)

    for index, wallet in enumerate(wallets):
        account_dir = data_dir / wallet.address
        account_dir.mkdir()

        balance = derive_balance(seed, index)
        nonce = derive_nonce(seed, index)

        (account_dir / "address").write_text(
            f"{wallet.address}\n",
            encoding="utf-8",
        )

        (account_dir / "balance").write_text(
            f"{balance}\n",
            encoding="utf-8",
        )

        (account_dir / "nonce").write_text(
            f"{nonce}\n",
            encoding="utf-8",
        )
