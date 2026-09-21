from pathlib import Path

import pytest

from modules.custody import request_custody
from modules.merkle import commit_state
from modules.peers import initialize_peers
from modules.storage import create_offer
from tests.helpers import Phase1Network


@pytest.fixture
def network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Phase1Network:
    monkeypatch.chdir(tmp_path)

    peers_dir = Path("data/peers")
    reference_dir = Path("data/reference")

    initialize_peers(
        7,
        peers_dir=peers_dir,
        reference_dir=reference_dir,
    )
    commit_state(
        peers_dir=peers_dir,
        reference_dir=reference_dir,
    )

    addresses = [
        path.name
        for path in sorted(
            peers_dir.iterdir(),
            key=lambda path: path.name.lower(),
        )
    ]
    publisher = addresses[0]
    custodians = addresses[1:6]
    spare = addresses[6]

    manifest = create_offer(
        publisher,
        encoding_type="erasure",
        peers_dir=peers_dir,
        reference_dir=reference_dir,
    )

    for custodian in custodians:
        request_custody(
            publisher_address=publisher,
            custodian_address=custodian,
            object_id=manifest["object_id"],
            peers_dir=peers_dir,
        )

    return Phase1Network(
        peers_dir=peers_dir,
        reference_dir=reference_dir,
        publisher=publisher,
        custodians=custodians,
        spare=spare,
        object_id=manifest["object_id"],
        manifest=manifest,
    )
