from modules.custody import parse_time, renew_custody
from tests.helpers import active_claims, load_custody


def test_distribution_replicates_complete_custody_view(network):
    expected = load_custody(network)

    assert len(active_claims(expected)) == 5

    for custodian in network.custodians:
        object_dir = network.object_dir(custodian)
        assert (object_dir / "manifest.json").is_file()
        assert (object_dir / "lease.json").is_file()
        assert load_custody(network, custodian) == expected


def test_custodian_renews_its_own_active_claim(network):
    custodian = network.custodians[0]
    before = load_custody(network)["0"]

    result = renew_custody(
        network.object_id,
        custodian,
        peers_dir=network.peers_dir,
    )
    after = load_custody(network)["0"]

    assert result["custodian"] == custodian
    assert parse_time(after["expires_at"]) > parse_time(
        before["expires_at"]
    )
    assert len(active_claims(load_custody(network))) == 5
