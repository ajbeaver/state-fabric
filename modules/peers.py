from pathlib import Path
import shutil

from modules.merkle import (
    generate_proof,
    load_account_dirs,
)


DEFAULT_ACCOUNTS_DIR = Path("data/accounts")
DEFAULT_REFERENCE_DIR = Path("data/reference")
DEFAULT_PEERS_DIR = Path("data/peers")


def initialize_peers(
    accounts_dir: Path = DEFAULT_ACCOUNTS_DIR,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
    peers_dir: Path = DEFAULT_PEERS_DIR,
) -> int:
    state_root = reference_dir / "state_root"

    if not state_root.exists():
        raise ValueError(
            "Canonical state root does not exist. "
            "Run commit before initializing peers."
        )

    account_dirs = load_account_dirs(accounts_dir)

    if peers_dir.exists():
        shutil.rmtree(peers_dir)

    peers_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    for account_dir in account_dirs:
        address = account_dir.name

        peer_dir = peers_dir / address
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

        shutil.copy2(
            account_dir / "balance",
            self_cache / "balance",
        )

        shutil.copy2(
            account_dir / "nonce",
            self_cache / "nonce",
        )

        generate_proof(
            address,
            accounts_dir=accounts_dir,
            reference_dir=reference_dir,
        )

        proof_source = (
            reference_dir
            / "proofs"
            / f"{address}.json"
        )

        shutil.copy2(
            proof_source,
            self_cache / "proof.json",
        )

    return len(account_dirs)
