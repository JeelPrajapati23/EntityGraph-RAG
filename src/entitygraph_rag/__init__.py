"""`entitygraph-rag` console script: serve the API (see api/app.py)."""

import argparse


def main() -> None:
    import uvicorn
    from dotenv import load_dotenv

    from .api import create_app

    parser = argparse.ArgumentParser(description="Serve the EntityGraph-RAG API and demo page.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    load_dotenv()
    uvicorn.run(create_app(), host=args.host, port=args.port)
