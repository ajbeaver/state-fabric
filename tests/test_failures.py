import pytest

from modules.custody import reconstruct_from_network, repair_network
from tests.helpers import (
    expire_claim,
    fragment_path,
    load_custody,
    repair_executor,
    valid_active_fragments,
)


def test_corrupt_fragment_is_rejected_but_others_reconstruct(network):
    fragment_path(network, 0).write_bytes(b"corrupt")

    valid_indices = {
        index
        for index, _, _, _ in valid_active_fragments(network)
    }

    assert 0 not in valid_indices
    assert len(valid_indices) == 4
    assert reconstruct_from_network(
        network.object_id,
        network.custodians[0],
        peers_dir=network.peers_dir,
    )


def test_missing_fragment_file_is_rejected_but_others_reconstruct(
    network,
):
    fragment_path(network, 0).unlink()

    valid_indices = {
        index
        for index, _, _, _ in valid_active_fragments(network)
    }

    assert 0 not in valid_indices
    assert len(valid_indices) == 4
    assert reconstruct_from_network(
        network.object_id,
        network.custodians[0],
        peers_dir=network.peers_dir,
    )


def test_reconstruction_and_repair_fail_below_threshold(network):
    for fragment_index in range(1, 5):
        fragment_path(network, fragment_index).unlink()

    executor = repair_executor(network)

    with pytest.raises(
        ValueError,
        match="Not enough valid network fragments",
    ):
        reconstruct_from_network(
            network.object_id,
            executor,
            peers_dir=network.peers_dir,
        )

    with pytest.raises(
        ValueError,
        match="Not enough valid active fragments",
    ):
        repair_network(
            network.object_id,
            executor,
            network.spare,
            peers_dir=network.peers_dir,
        )


def test_capacity_failure_does_not_publish_false_claim(network):
    expire_claim(network, 0)
    executor = repair_executor(network)
    custody_paths = list(
        network.peers_dir.glob(
            f"*/data/{network.object_id}/custody.json"
        )
    )
    before = {
        path: path.read_text(encoding="utf-8")
        for path in custody_paths
    }

    (network.peers_dir / network.spare / "capacity").write_text(
        "0\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="enough capacity"):
        repair_network(
            network.object_id,
            executor,
            network.spare,
            peers_dir=network.peers_dir,
        )

    assert not network.object_dir(network.spare).exists()
    assert all(
        path.read_text(encoding="utf-8") == content
        for path, content in before.items()
    )
    assert all(
        claim["custodian"] != network.spare
        for claim in load_custody(network, executor).values()
    )
