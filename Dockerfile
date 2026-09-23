# reachfix API + demo page, deployed on Render from a prebuilt image (data/ is gitignored, so the
# image is built locally, where the build outputs exist, and pushed to ghcr.io):
#   docker build -t ghcr.io/jeelprajapati23/reachfix . && docker push ghcr.io/jeelprajapati23/reachfix
#   docker run --rm -p 7860:7860 --env-file .env ghcr.io/jeelprajapati23/reachfix   # local check
# GROQ_API_KEY and HF_TOKEN come from the environment (host secrets); no key is baked in.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Non-root; the live OSV / registry caches are written under data/raw/.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/app/.venv/bin:$PATH \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1
WORKDIR /home/user/app

# Dependencies first, so code/data changes don't reinstall them.
COPY --chown=user pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=user src ./src
COPY --chown=user schema ./schema
COPY --chown=user config ./config
RUN uv sync --frozen --no-dev

# Only what the API loads (api/resources.py): graph, node lookup, advisory chunks + index, releases.
COPY --chown=user data/processed/depgraph/graph.pkl \
     data/processed/depgraph/nodes.jsonl \
     data/processed/depgraph/advisory_chunks.jsonl \
     data/processed/depgraph/advisory_index_minilm_windowed.ids.json \
     data/processed/depgraph/advisory_index_minilm_windowed.vectors.npy \
     data/processed/depgraph/releases.json \
     ./data/processed/depgraph/

# /query spends Groq tokens shared by every visitor (see api/ratelimit.py).
ENV REACHFIX_QUERY_LIMIT_PER_IP_HOUR=10 \
    REACHFIX_QUERY_LIMIT_PER_DAY=100

# Render sets PORT itself; 7860 is the local default.
ENV PORT=7860
EXPOSE 7860
CMD ["reachfix", "--host", "0.0.0.0"]
