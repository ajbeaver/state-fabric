import logging
import argparse


APP_NAME = "state-fabric"
VERSION = "v0.0.1"

LINE_01 = "=" * 20
LINE_02 = "-" * 40

# Add third-party logger names used by the project.
# Example:
# LIBRARY_LOGGERS = ["web3", "urllib3"]
LIBRARY_LOGGERS = []


def setup_logging(verbosity=0):
    levels = {
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG,
        3: logging.DEBUG,
    }

    level = levels.get(min(verbosity, 3), logging.DEBUG)

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # At -vv, show project DEBUG while suppressing dependency DEBUG.
    # At -vvv, allow dependency DEBUG output too.
    for name in LIBRARY_LOGGERS:
        if verbosity < 3:
            logging.getLogger(name).setLevel(logging.WARNING)
        else:
            logging.getLogger(name).setLevel(logging.NOTSET)


logger = logging.getLogger(__name__)

def banner():
    print(LINE_01)
    print(f"  {APP_NAME}")
    print(f"  {VERSION}")
    print(LINE_01)
    print()


def build_parser():
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="PROJECT_DESCRIPTION",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase logging verbosity",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    # Add project-specific arguments here.

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(args.verbose)
    banner()

    logger.debug("Arguments: %s", args)

    # Begin project-specific logic here.

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
