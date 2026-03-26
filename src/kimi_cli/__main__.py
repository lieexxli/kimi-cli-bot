from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env file from the current directory or project root if present."""
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)  # don't override already-set env vars
    except ImportError:
        pass  # python-dotenv not installed, skip silently


def _prog_name() -> str:
    return Path(sys.argv[0]).name or "kimi"


def main(argv: Sequence[str] | None = None) -> int | str | None:
    _load_dotenv()
    args = list(sys.argv[1:] if argv is None else argv)

    if len(args) == 1 and args[0] in {"--version", "-V"}:
        from kimi_cli.constant import get_version

        print(f"kimi, version {get_version()}")
        return 0

    from kimi_cli.cli import cli

    try:
        return cli(args=args, prog_name=_prog_name())
    except SystemExit as exc:
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
