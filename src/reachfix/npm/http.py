"""Shared HTTP helper for the OSV and npm registry fetch scripts."""

import time

import requests

USER_AGENT = "reachfix research project (github.com/JeelPrajapati23/reachfix)"
MAX_RETRIES = 5


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def request_json(session: requests.Session, method: str, url: str, **kwargs) -> dict:
    """Retry connection errors, 429s and 5xx with exponential backoff; raise other HTTP errors at once."""
    for attempt in range(MAX_RETRIES):
        last_try = attempt == MAX_RETRIES - 1
        try:
            resp = session.request(method, url, timeout=120, **kwargs)
        except (requests.ConnectionError, requests.Timeout):
            if last_try:
                raise
        else:
            if resp.status_code != 429 and resp.status_code < 500:
                resp.raise_for_status()
                return resp.json()
            if last_try:
                resp.raise_for_status()
        time.sleep(2**attempt)
    raise AssertionError("unreachable")
