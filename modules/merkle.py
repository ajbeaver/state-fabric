from pathlib import Path
import json

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


def load_account_dirs(
    accounts_dir: Path = DEFAULT_ACCOUNTS_DIR,
) -> list[Path]:
    if not accounts_dir.exists():
        raise ValueError(
            f"Accounts directory does not exist: {accounts_dir}"
        )

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

    return account_dirs


def load_leaf_hashes(
    accounts_dir: Path = DEFAULT_ACCOUNTS_DIR,
) -> list[bytes]:
    account_dirs = load_account_dirs(accounts_dir)

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

    reference_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    root_hex = f"0x{root.hex()}"

    (reference_dir / "state_root").write_text(
        f"{root_hex}\n",
        encoding="utf-8",
    )

    return root


def find_account_dir(
    address: str,
    accounts_dir: Path = DEFAULT_ACCOUNTS_DIR,
) -> Path:
    account_dirs = load_account_dirs(accounts_dir)

    for account_dir in account_dirs:
        if account_dir.name.lower() == address.lower():
            return account_dir

    raise ValueError(
        f"Account not found: {address}"
    )


def generate_proof(
    address: str,
    accounts_dir: Path = DEFAULT_ACCOUNTS_DIR,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> list[dict[str, str]]:
    account_dirs = load_account_dirs(accounts_dir)

    target_index = None

    for index, account_dir in enumerate(account_dirs):
        if account_dir.name.lower() == address.lower():
            target_index = index
            break

    if target_index is None:
        raise ValueError(
            f"Account not found: {address}"
        )

    level = [
        hash_account(account_dir)
        for account_dir in account_dirs
    ]

    proof = []
    index = target_index

    while len(level) > 1:
        if len(level) % 2 != 0:
            level.append(level[-1])

        if index % 2 == 0:
            sibling_index = index + 1
            side = "right"
        else:
            sibling_index = index - 1
            side = "left"

        sibling_hash = level[sibling_index]

        proof.append(
            {
                "side": side,
                "hash": f"0x{sibling_hash.hex()}",
            }
        )

        next_level = []

        for pair_index in range(0, len(level), 2):
            left = level[pair_index]
            right = level[pair_index + 1]

            parent = keccak(left + right)
            next_level.append(parent)

        level = next_level
        index //= 2

    proofs_dir = reference_dir / "proofs"

    proofs_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    canonical_address = account_dirs[target_index].name

    proof_data = {
        "address": canonical_address,
        "proof": proof,
    }

    proof_path = proofs_dir / f"{canonical_address}.json"

    proof_path.write_text(
        json.dumps(
            proof_data,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return proof


def load_proof(
    address: str,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> list[dict[str, str]]:
    proofs_dir = reference_dir / "proofs"

    if not proofs_dir.exists():
        raise ValueError(
            "Proof directory does not exist"
        )

    proof_path = None

    for candidate in proofs_dir.glob("*.json"):
        if candidate.stem.lower() == address.lower():
            proof_path = candidate
            break

    if proof_path is None:
        raise ValueError(
            f"Proof not found: {address}"
        )

    proof_data = json.loads(
        proof_path.read_text(
            encoding="utf-8"
        )
    )

    if proof_data["address"].lower() != address.lower():
        raise ValueError(
            "Proof address does not match requested address"
        )

    return proof_data["proof"]


def load_state_root(
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> bytes:
    root_path = reference_dir / "state_root"

    if not root_path.exists():
        raise ValueError(
            "State root does not exist"
        )

    root_hex = root_path.read_text(
        encoding="utf-8"
    ).strip()

    if root_hex.startswith("0x"):
        root_hex = root_hex[2:]

    root = bytes.fromhex(root_hex)

    if len(root) != 32:
        raise ValueError(
            "State root must be 32 bytes"
        )

    return root


def verify_proof(
    account_dir: Path,
    proof: list[dict[str, str]],
    expected_root: bytes,
) -> bool:
    current_hash = hash_account(account_dir)

    for proof_item in proof:
        side = proof_item["side"]
        sibling_hex = proof_item["hash"]

        if sibling_hex.startswith("0x"):
            sibling_hex = sibling_hex[2:]

        sibling_hash = bytes.fromhex(
            sibling_hex
        )

        if len(sibling_hash) != 32:
            raise ValueError(
                "Merkle proof hash must be 32 bytes"
            )

        if side == "left":
            current_hash = keccak(
                sibling_hash + current_hash
            )

        elif side == "right":
            current_hash = keccak(
                current_hash + sibling_hash
            )

        else:
            raise ValueError(
                f"Invalid proof side: {side}"
            )

    return current_hash == expected_root


def verify_account(
    address: str,
    accounts_dir: Path = DEFAULT_ACCOUNTS_DIR,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> bool:
    account_dir = find_account_dir(
        address,
        accounts_dir,
    )

    proof = load_proof(
        address,
        reference_dir,
    )

    state_root = load_state_root(
        reference_dir,
    )

    return verify_proof(
        account_dir,
        proof,
        state_root,
    )
