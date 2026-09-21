import json
import shutil

from dataclasses import dataclass
from pathlib import Path

from modules.custody import (
    format_time,
    get_manifest_fragment,
    get_valid_active_fragments,
    parse_time,
    utc_now,
)


@dataclass
class Phase1Network:
    peers_dir: Path
    reference_dir: Path
    publisher: str
    custodians: list[str]
    spare: str
    object_id: str
    manifest: dict

    def object_dir(self, peer: str) -> Path:
        return self.peers_dir / peer / "data" / self.object_id


def load_custody(
    network: Phase1Network,
    peer: str | None = None,
) -> dict:
    if peer is None:
        peer = network.custodians[0]

    return json.loads(
        (network.object_dir(peer) / "custody.json").read_text(
            encoding="utf-8"
        )
    )


def expire_claim(
    network: Phase1Network,
    fragment_index: int,
) -> None:
    expired_at = "2000-01-01T00:00:00Z"

    for custody_path in network.peers_dir.glob(
        f"*/data/{network.object_id}/custody.json"
    ):
        custody = json.loads(
            custody_path.read_text(encoding="utf-8")
        )
        custody[str(fragment_index)]["expires_at"] = expired_at
        custody_path.write_text(
            json.dumps(custody, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def active_claims(custody: dict) -> dict:
    now = utc_now()

    return {
        fragment_key: claim
        for fragment_key, claim in custody.items()
        if (
            claim["status"] == "leased"
            and parse_time(claim["expires_at"]) > now
        )
    }


def valid_active_fragments(
    network: Phase1Network,
    peer: str | None = None,
):
    return get_valid_active_fragments(
        network.object_id,
        network.manifest,
        load_custody(network, peer),
        network.peers_dir,
    )


def repair_executor(
    network: Phase1Network,
    peer: str | None = None,
) -> str:
    addresses = {
        lease["custodian"]
        for _, lease, _, _ in valid_active_fragments(network, peer)
    }
    return min(addresses, key=str.lower)


def fragment_path(
    network: Phase1Network,
    fragment_index: int,
    peer: str | None = None,
) -> Path:
    custody = load_custody(network, peer)
    custodian = custody[str(fragment_index)]["custodian"]
    fragment = get_manifest_fragment(
        network.manifest,
        fragment_index,
    )
    return network.object_dir(custodian) / fragment["filename"]


def remove_publisher(network: Phase1Network) -> None:
    shutil.rmtree(network.peers_dir / network.publisher)
