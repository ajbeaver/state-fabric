from pathlib import Path

from eth_utils import keccak


DEFAULT_ACCOUNTS_DIR = Path("data/accounts")
DEFAULT_REFERENCE_DIR = Path("data/reference")


def serialize_account(account_dir: Path) -> bytes:
    address = (account_dir / "address").read_text(
        encoding="utf-8"
    ).strip()

    balance = int(
        (account_dir / "balance").read_text(
            encoding="utf-8"
        ).strip()
    )

    nonce = int(
        (account_dir / "nonce").read_text(
            encoding="utf-8"
        ).strip()
    )

    if address.lower() != account_dir.name.lower():
        raise ValueError(
            f"Address mismatch in {account_dir}"
        )

    canonical = (
        f"address={address.lower()}\n"
        f"balance={balance}\n"
        f"nonce={nonce}\n"
    )

    return canonical.encode("utf-8")


def hash_account(account_dir: Path) -> bytes:
    account_bytes = serialize_account(account_dir)

    return keccak(account_bytes)


def load_leaf_hashes(
    accounts_dir: Path = DEFAULT_ACCOUNTS_DIR,
) -> list[bytes]:
    account_dirs = sorted(
        (
            path
            for path in accounts_dir.iterdir()
            if path.is_dir()
        ),
        key=lambda path: path.name.lower(),
    )

    if not account_dirs:
        raise ValueError("No accounts found")

    return [
        hash_account(account_dir)
        for account_dir in account_dirs
    ]


def build_merkle_root(leaves: list[bytes]) -> bytes:
    if not leaves:
        raise ValueError("Cannot build tree without leaves")

    level = list(leaves)

    while len(level) > 1:
        if len(level) % 2 != 0:
            level.append(level[-1])

        next_level = []

        for index in range(0, len(level), 2):
            left = level[index]
            right = level[index + 1]

            parent = keccak(left + right)
            next_level.append(parent)

        level = next_level

    return level[0]


def commit_state(
    accounts_dir: Path = DEFAULT_ACCOUNTS_DIR,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> bytes:
    leaves = load_leaf_hashes(accounts_dir)
    root = build_merkle_root(leaves)

    reference_dir.mkdir(parents=True, exist_ok=True)

    root_hex = f"0x{root.hex()}"

    (reference_dir / "state_root").write_text(
        f"{root_hex}\n",
        encoding="utf-8",
    )

    return root
