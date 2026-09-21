import argparse
from pathlib import Path

from modules.custody import (
    request_custody,
    reconstruct_from_custody,
)
from modules.peers import initialize_peers
from modules.merkle import (
    commit_state,
    verify_peer,
)
from modules.storage import (
    create_offer,
    reconstruct_offer,
    get_object_id,
    parse_state_package,
)


DEFAULT_PEERS_DIR = Path("data/peers")


def build_parser():
    parser = argparse.ArgumentParser(
        description="State Fabric research simulator"
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    init_parser = commands.add_parser(
        "init",
        help="Initialize simulated peer devices",
    )

    init_parser.add_argument(
        "--peers",
        type=int,
        default=10,
        help="Number of peers to generate",
    )

    commands.add_parser(
        "commit",
        help="Commit peer state and generate proofs",
    )

    verify_parser = commands.add_parser(
        "verify",
        help="Verify a peer's cached state against the state root",
    )

    verify_parser.add_argument(
        "--address",
        required=True,
        help="Ethereum address of the peer to verify",
    )

    offer_parser = commands.add_parser(
        "offer",
        help="Create a fragmented state offer for a peer",
    )

    offer_parser.add_argument(
        "--address",
        required=True,
        help="Ethereum address publishing the offer",
    )

    offer_parser.add_argument(
        "--encoding",
        choices=[
            "stripe",
            "erasure",
        ],
        default="erasure",
        help="Fragment encoding method",
    )

    offer_parser.add_argument(
        "--fragments",
        type=int,
        default=4,
        help="Fragment count for plain striping",
    )

    custody_parser = commands.add_parser(
        "request-custody",
        help="Request and store one fragment from a publisher",
    )

    custody_parser.add_argument(
        "--publisher",
        required=True,
        help="Address of the peer publishing the offer",
    )

    custody_parser.add_argument(
        "--custodian",
        required=True,
        help="Address of the peer accepting custody",
    )

    custody_parser.add_argument(
        "--object-id",
        help="Specific object ID to request custody from",
    )

    reconstruct_parser = commands.add_parser(
        "reconstruct",
        help="Reconstruct a state package from an offer",
    )

    reconstruct_parser.add_argument(
        "--address",
        required=True,
        help="Ethereum address that published the offer",
    )

    reconstruct_parser.add_argument(
        "--object-id",
        help="Specific object ID to reconstruct",
    )

    drop_parser = commands.add_parser(
        "drop-fragment",
        help="Delete one fragment for failure testing",
    )

    drop_parser.add_argument(
        "--address",
        required=True,
        help="Ethereum address that published the offer",
    )

    drop_parser.add_argument(
        "--index",
        type=int,
        required=True,
        help="Fragment index to delete",
    )

    drop_parser.add_argument(
        "--object-id",
        help="Specific object ID containing the fragment",
    )

    custody_reconstruct_parser = commands.add_parser(
        "reconstruct-custody",
        help="Reconstruct an object from leased custodian fragments",
    )
    
    custody_reconstruct_parser.add_argument(
        "--publisher",
        required=True,
        help="Address of the peer that published the object",
    )
    
    custody_reconstruct_parser.add_argument(
        "--object-id",
        help="Specific object ID to reconstruct",
    )

    return parser


def find_offer_dir(
    address: str,
    object_id: str | None = None,
) -> Path:
    peer_dir = None

    if not DEFAULT_PEERS_DIR.exists():
        raise ValueError(
            "Peers directory does not exist"
        )

    for candidate in DEFAULT_PEERS_DIR.iterdir():
        if (
            candidate.is_dir()
            and candidate.name.lower() == address.lower()
        ):
            peer_dir = candidate
            break

    if peer_dir is None:
        raise ValueError(
            f"Peer not found: {address}"
        )

    offers_dir = (
        peer_dir
        / "offers"
    )

    if not offers_dir.exists():
        raise ValueError(
            f"No offers found for {address}"
        )

    if object_id:
        offer_dir = (
            offers_dir
            / object_id
        )

        if not offer_dir.exists():
            raise ValueError(
                f"Offer not found: {object_id}"
            )

        return offer_dir

    offers = sorted(
        (
            path
            for path in offers_dir.iterdir()
            if path.is_dir()
        ),
        key=lambda path: path.name,
    )

    if not offers:
        raise ValueError(
            f"No offers found for {address}"
        )

    if len(offers) > 1:
        raise ValueError(
            "Multiple offers found. "
            "Specify --object-id."
        )

    return offers[0]


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        count = initialize_peers(
            args.peers
        )

        print(
            f"Initialized {count} peers "
            "in data/peers/"
        )

    elif args.command == "commit":
        root = commit_state()

        print(
            f"State root: 0x{root.hex()}"
        )

        print(
            "Generated proofs for all peers"
        )

    elif args.command == "verify":
        valid = verify_peer(
            args.address
        )

        if valid:
            print(
                f"Verified: {args.address}"
            )
        else:
            print(
                f"Verification failed: "
                f"{args.address}"
            )

    elif args.command == "offer":
        manifest = create_offer(
            args.address,
            encoding_type=args.encoding,
            fragment_count=args.fragments,
        )

        encoding = manifest[
            "encoding"
        ]

        print(
            f"Created offer for "
            f"{args.address}"
        )

        print(
            f"Object ID: "
            f"{manifest['object_id']}"
        )

        print(
            f"Object size: "
            f"{manifest['original_size']} bytes"
        )

        print(
            f"Encoding: "
            f"{encoding['type']}"
        )

        print(
            f"Fragments: "
            f"{encoding['total_fragments']}"
        )

        print(
            f"Required: "
            f"{encoding['required_fragments']}"
        )

    elif args.command == "request-custody":
        result = request_custody(
            publisher_address=(
                args.publisher
            ),
            custodian_address=(
                args.custodian
            ),
            object_id=(
                args.object_id
            ),
        )

        print(
            f"Publisher: "
            f"{result['publisher']}"
        )

        print(
            f"Custodian: "
            f"{result['custodian']}"
        )

        print(
            f"Object ID: "
            f"{result['object_id']}"
        )

        print(
            f"Fragment: "
            f"{result['fragment_filename']}"
        )

        print(
            f"Fragment size: "
            f"{result['fragment_size']} bytes"
        )

        print(
            "Fragment verification: passed"
        )

        print(
            "Lease status: "
            f"{result['lease']['status']}"
        )

        print(
            "Lease expires: "
            f"{result['lease']['expires_at']}"
        )

        print(
            f"Stored at: "
            f"{result['destination']}"
        )

    elif args.command == "reconstruct":
        offer_dir = find_offer_dir(
            args.address,
            args.object_id,
        )

        package = reconstruct_offer(
            offer_dir
        )

        parsed = parse_state_package(
            package
        )

        print(
            f"Reconstructed: "
            f"{parsed['address']}"
        )

        print(
            f"Size: "
            f"{len(package)} bytes"
        )

        print(
            f"Object ID: "
            f"{get_object_id(package)}"
        )

        print(
            "Canonical verification: passed"
        )

    elif args.command == "reconstruct-custody":
        package = reconstruct_from_custody(
            publisher_address=(
                args.publisher
            ),
            object_id=(
                args.object_id
            ),
        )
    
        parsed = parse_state_package(
            package
        )
    
        print(
            f"Reconstructed: "
            f"{parsed['address']}"
        )
    
        print(
            f"Size: "
            f"{len(package)} bytes"
        )
    
        print(
            f"Object ID: "
            f"{get_object_id(package)}"
        )
    
        print(
            "Source: custodian network"
        )
    
        print(
            "Canonical verification: passed"
        )

    elif args.command == "drop-fragment":
        offer_dir = find_offer_dir(
            args.address,
            args.object_id,
        )

        fragment_path = (
            offer_dir
            / "fragments"
            / f"{args.index:03d}.bin"
        )

        if not fragment_path.exists():
            raise ValueError(
                f"Fragment does not exist: "
                f"{fragment_path.name}"
            )

        fragment_path.unlink()

        print(
            f"Deleted fragment "
            f"{args.index:03d}.bin"
        )


if __name__ == "__main__":
    main()
