import argparse

from modules.peers import initialize_peers
from modules.merkle import (
    commit_state,
    verify_peer,
)


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

    return parser


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


if __name__ == "__main__":
    main()
