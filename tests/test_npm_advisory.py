from entitygraph_rag.npm.advisory import chunk_advisory, is_malicious, markdown_sections

DETAILS = """Intro line before any heading.

### Impact

Only exploitable when `maxRedirects` is raised
above the default.

### PoC

```js
const a = 1;

const b = 2;
```

### Patches
Fixed in 1.14.7.
"""

RECORD = {
    "id": "GHSA-74fj-2j2h-c42q",
    "aliases": ["CVE-2022-0155"],
    "summary": "Exposure of private information in follow-redirects",
    "modified": "2024-01-01T00:00:00Z",
    "database_specific": {"severity": "HIGH"},
    "affected": [{"package": {"ecosystem": "npm", "name": "follow-redirects"}}],
    "details": DETAILS,
}


def test_markdown_sections_split_at_headings_and_keep_code_fences_whole():
    sections = markdown_sections(DETAILS)

    assert [h for h, _ in sections] == ["", "Impact", "PoC", "Patches"]
    assert sections[1][1] == ["Only exploitable when `maxRedirects` is raised\nabove the default."]
    assert sections[2][1] == ["```js\nconst a = 1;\n\nconst b = 2;\n```"]
    assert sections[3][1] == ["Fixed in 1.14.7."]


def test_short_advisory_is_one_chunk_with_provenance():
    [chunk] = chunk_advisory(RECORD)

    assert chunk.chunk_id == "GHSA-74fj-2j2h-c42q::0"
    assert chunk.source_url == "https://osv.dev/vulnerability/GHSA-74fj-2j2h-c42q"
    assert (chunk.aliases, chunk.severity, chunk.affected_packages) == (["CVE-2022-0155"], "HIGH", ["follow-redirects"])
    assert chunk.sections == ["", "Impact", "PoC", "Patches"]
    assert "### Impact\n\nOnly exploitable" in chunk.text
    assert "const a = 1;\n\nconst b = 2;" in chunk.text


def test_long_advisory_packs_across_headings_without_orphan_headings():
    chunks = chunk_advisory(RECORD, max_words=12)

    assert [c.chunk_id for c in chunks] == [f"GHSA-74fj-2j2h-c42q::{i}" for i in range(len(chunks))]
    assert len(chunks) > 1
    for c in chunks:
        # A heading is always followed by its paragraph in the same chunk.
        assert not c.text.rstrip().split("\n")[-1].startswith("###")
    assert chunks[-1].sections[-1] == "Patches"


def test_chunk_ids_are_stable_across_runs():
    assert [c.chunk_id for c in chunk_advisory(RECORD, 12)] == [c.chunk_id for c in chunk_advisory(RECORD, 12)]


def test_malicious_package_records_are_flagged():
    assert is_malicious({"id": "MAL-2023-462"})
    assert not is_malicious(RECORD)
