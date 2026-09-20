import argparse

from modules.accounts import initialize_accounts
from modules.merkle import commit_state


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

        print(f"State root: 0x{root.hex()}")


if __name__ == "__main__":
    main()
