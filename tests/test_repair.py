import pytest
from eth_utils import keccak

from modules.custody import (
    get_manifest_fragment,
    reconstruct_from_network,
    repair_network,
)
from modules.storage import verify_state_package
from tests.helpers import (
    active_claims,
    expire_claim,
    load_custody,
    repair_executor,
    valid_active_fragments,
)


def test_expired_claim_is_missing_and_repair_restores_health(network):
    expire_claim(network, 0)

    assert {
        index
        for index, _, _, _ in valid_active_fragments(network)
    } == {1, 2, 3, 4}

    executor = repair_executor(network)
    result = repair_network(
        network.object_id,
        executor,
        network.spare,
        peers_dir=network.peers_dir,
    )

    custody = load_custody(network, executor)
    fragment = get_manifest_fragment(network.manifest, 0)
    regenerated = (
        network.object_dir(network.spare)
        / fragment["filename"]
    ).read_bytes()

    assert result["fragment_index"] == 0
    assert len(active_claims(custody)) == 5
    assert f"0x{keccak(regenerated).hex()}" == fragment["hash"]

    package = reconstruct_from_network(
        network.object_id,
        executor,
        peers_dir=network.peers_dir,
    )
    assert verify_state_package(
        package,
        reference_dir=network.reference_dir,
    )


def test_expired_former_custodian_can_reenter(network):
    former = network.custodians[0]
    expire_claim(network, 0)
    executor = repair_executor(network)

    repair_network(
        network.object_id,
        executor,
        former,
        peers_dir=network.peers_dir,
    )

    active = active_claims(load_custody(network, executor))

    assert len(active) == 5
    assert sum(
        claim["custodian"].lower() == former.lower()
        for claim in active.values()
    ) == 1


def test_wrong_repair_executor_identifies_correct_peer(network):
    expire_claim(network, 0)
    executor = repair_executor(network)
    wrong_peer = next(
        lease["custodian"]
        for _, lease, _, _ in valid_active_fragments(network)
        if lease["custodian"].lower() != executor.lower()
    )

    with pytest.raises(ValueError, match=executor):
        repair_network(
            network.object_id,
            wrong_peer,
            network.spare,
            peers_dir=network.peers_dir,
        )

    assert not network.object_dir(network.spare).exists()
