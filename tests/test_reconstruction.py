import shutil

from modules.custody import reconstruct_from_network
from modules.storage import verify_state_package
from tests.helpers import remove_publisher


def test_healthy_network_reconstructs_and_verifies(network):
    package = reconstruct_from_network(
        network.object_id,
        network.custodians[0],
        peers_dir=network.peers_dir,
    )

    assert verify_state_package(
        package,
        reference_dir=network.reference_dir,
    )


def test_reconstruction_is_publisher_independent(network):
    remove_publisher(network)

    package = reconstruct_from_network(
        network.object_id,
        network.custodians[0],
        peers_dir=network.peers_dir,
    )

    assert verify_state_package(
        package,
        reference_dir=network.reference_dir,
    )


def test_reconstruction_survives_missing_custodian(network):
    shutil.rmtree(
        network.peers_dir / network.custodians[0]
    )

    package = reconstruct_from_network(
        network.object_id,
        network.custodians[1],
        peers_dir=network.peers_dir,
    )

    assert verify_state_package(
        package,
        reference_dir=network.reference_dir,
    )
