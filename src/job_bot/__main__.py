"""Command-line entry point for the project scaffold."""

from argparse import ArgumentParser
from importlib.metadata import version


def main() -> None:
    """Display scaffold usage without starting network services."""
    parser = ArgumentParser(
        prog="job-bot",
        description=(
            "Telegram job search bot scaffold. "
            "Telegram polling and Work.ua searches are not implemented yet."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('job-searcher')}"
    )
    parser.parse_args()
    parser.print_help()


if __name__ == "__main__":
    main()
