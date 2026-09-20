from dataclasses import dataclass

from eth_account import Account
from eth_utils import keccak


SECP256K1_ORDER = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
)


@dataclass(frozen=True)
class Wallet:
    address: str


def derive_private_key(seed: str, index: int) -> bytes:
    material = f"{seed}:{index}".encode("utf-8")
    digest = keccak(material)

    key_number = int.from_bytes(digest, byteorder="big")
    key_number = (key_number % (SECP256K1_ORDER - 1)) + 1

    return key_number.to_bytes(32, byteorder="big")


def generate_wallets(count: int, seed: str = "state-fabric-v1") -> list[Wallet]:
    wallets = []

    for index in range(count):
        private_key = derive_private_key(seed, index)
        account = Account.from_key(private_key)

        wallets.append(
            Wallet(
                address=account.address,
            )
        )

    return wallets
