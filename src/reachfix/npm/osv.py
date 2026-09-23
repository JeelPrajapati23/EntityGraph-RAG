"""OSV.dev record helpers."""


def normalize_modified(ts: str) -> str:
    """Truncate an OSV `modified` timestamp to microseconds.

    /v1/querybatch reports microseconds ("…:10.642592Z") but /v1/vulns/{id}
    reports nanoseconds ("…:10.642592133Z") for the same instant, so the raw
    strings never compare equal.
    """
    body = ts.rstrip("Z")
    if "." in body:
        whole, frac = body.split(".", 1)
        body = f"{whole}.{frac[:6].ljust(6, '0')}"
    return body + "Z"
