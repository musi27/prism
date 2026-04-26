"""Entry point: python3 serve.py [--host HOST] [--port PORT]"""
import argparse
import os

from ui.server import main


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Prism UI server.")
    parser.add_argument(
        "--host",
        default=os.environ.get("PRISM_UI_HOST") or "localhost",
        help="Host to bind (default: localhost; or PRISM_UI_HOST env)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PRISM_UI_PORT") or "4242"),
        help="Port to bind (default: 4242; or PRISM_UI_PORT env)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(args.host, args.port)
