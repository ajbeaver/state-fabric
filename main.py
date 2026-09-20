import argparse

from modules.accounts import initialize_accounts
from modules.merkle import (
    commit_state,
    generate_proof,
    verify_account,
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
        help="Initialize account state",
    )

    init_parser.add_argument(
        "--accounts",
        type=int,
        default=10,
        help="Number of accounts to generate",
    )

    commands.add_parser(
        "commit",
        help="Calculate the canonical state root",
    )

    prove_parser = commands.add_parser(
        "prove",
        help="Generate a Merkle proof for an account",
    )

    prove_parser.add_argument(
        "--address",
        required=True,
        help="Ethereum address to generate a proof for",
    )

    verify_parser = commands.add_parser(
        "verify",
        help="Verify an account against the canonical state root",
    )

    verify_parser.add_argument(
        "--address",
        required=True,
        help="Ethereum address to verify",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        initialize_accounts(args.accounts)

        print(
            f"Initialized {args.accounts} accounts "
            "in data/accounts/"
        )

    elif args.command == "commit":
        root = commit_state()

        print(
            f"State root: 0x{root.hex()}"
        )

    elif args.command == "prove":
        proof = generate_proof(
            args.address
        )

        print(
            f"Generated proof for {args.address}"
        )

        print(
            f"Proof contains {len(proof)} sibling hashes"
        )

    elif args.command == "verify":
        valid = verify_account(
            args.address
        )

        if valid:
            print(
                f"Verified: {args.address}"
            )
        else:
            print(
                f"Verification failed: {args.address}"
            )


if __name__ == "__main__":
    main()
