"""``python -m cap_backend`` entrypoint."""

from __future__ import annotations

import argparse
import sys

from cap_backend.app import build_app
from cap_backend.config import load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cap-backend")
    parser.add_argument(
        "--config",
        help="Path to config.yaml. Overrides CAP_CONFIG and the default search.",
        default=None,
    )
    args = parser.parse_args(argv)

    settings = load_settings(args.config)
    app = build_app(settings)

    runx = getattr(app, "runx", None)
    if runx is not None:
        runx(host=settings.server.host, port=settings.server.port)
    else:
        app.run(host=settings.server.host, port=settings.server.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
