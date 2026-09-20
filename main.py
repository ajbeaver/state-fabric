import argparse

from modules.accounts import initialize_accounts


def build_parser():
    parser = argparse.ArgumentParser(
        description="State Fabric research simulator"
    )

    parser.add_argument(
        "--accounts",
        type=int,
        default=10,
        help="Number of accounts to generate",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    initialize_accounts(args.accounts)

    print(f"Initialized {args.accounts} accounts in data/accounts/")


if __name__ == "__main__":
    main()
