"""`reachfix` console script: serve the API (see api/app.py)."""

import argparse
import os


def main() -> None:
    import uvicorn
    from dotenv import load_dotenv

    from .api import create_app

    parser = argparse.ArgumentParser(description="Serve the reachfix API and demo page.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))  # hosts like Render set PORT
    args = parser.parse_args()

    load_dotenv()
    uvicorn.run(create_app(), host=args.host, port=args.port)
