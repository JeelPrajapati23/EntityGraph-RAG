import json

import pytest

from entitygraph_rag.npm.corpus import corpus_name_versions, versions_by_name
from entitygraph_rag.npm.lockfile import installed_packages, load_lockfile, name_from_path, unique_name_versions

LOCK = {
    "name": "depgraph-scratch",
    "lockfileVersion": 3,
    "packages": {
        "": {"name": "depgraph-scratch", "dependencies": {"axios": "^0.21.1"}},
        "node_modules/axios": {
            "version": "0.21.1",
            "resolved": "https://registry.npmjs.org/axios/-/axios-0.21.1.tgz",
            "dependencies": {"follow-redirects": "^1.10.0"},
        },
        "node_modules/follow-redirects": {"version": "1.13.1", "peerDependencies": {"debug": "*"}},
        "node_modules/axios/node_modules/@scope/inner": {"version": "2.0.0", "optional": True},
        "node_modules/string-width-cjs": {"name": "string-width", "version": "4.2.3"},
        "packages/local": {"version": "1.0.0"},
        "node_modules/local": {"resolved": "packages/local", "link": True},
    },
}


def write_lock(tmp_path, lock=LOCK, subdir="a"):
    path = tmp_path / subdir / "package-lock.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock), encoding="utf-8")
    return path


def test_name_from_path_handles_nesting_and_scopes():
    assert name_from_path("node_modules/axios") == "axios"
    assert name_from_path("node_modules/a/node_modules/@scope/inner") == "@scope/inner"
    with pytest.raises(ValueError):
        name_from_path("packages/local")


def test_installed_packages_skips_root_and_links():
    by_path = {p.path: p for p in installed_packages(LOCK)}

    assert "" not in by_path
    assert "node_modules/local" not in by_path
    assert by_path["node_modules/axios"].dependencies == {"follow-redirects": "^1.10.0"}
    assert by_path["node_modules/axios/node_modules/@scope/inner"].optional is True
    assert by_path["node_modules/follow-redirects"].peer_dependencies == {"debug": "*"}


def test_installed_packages_uses_real_name_for_aliases():
    by_path = {p.path: p for p in installed_packages(LOCK)}

    assert by_path["node_modules/string-width-cjs"].name == "string-width"


def test_workspace_source_dirs_are_not_registry_packages():
    assert unique_name_versions(installed_packages(LOCK)) == {
        ("axios", "0.21.1"),
        ("follow-redirects", "1.13.1"),
        ("@scope/inner", "2.0.0"),
        ("string-width", "4.2.3"),
    }


def test_lockfile_v1_is_rejected(tmp_path):
    path = write_lock(tmp_path, {"lockfileVersion": 1, "dependencies": {}})
    with pytest.raises(ValueError, match="need v2 or v3"):
        load_lockfile(path)


def test_corpus_name_versions_tracks_which_lockfiles_contain_each_version(tmp_path):
    a = write_lock(tmp_path, subdir="a")
    b = write_lock(tmp_path, {"lockfileVersion": 3, "packages": {"node_modules/axios": {"version": "0.21.1"}}}, "b")
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            json.dumps({"doc_id": doc_id, "local_path": p.relative_to(tmp_path).as_posix()})
            for doc_id, p in [("lock:a", a), ("lock:b", b)]
        ),
        encoding="utf-8",
    )

    corpus = corpus_name_versions(manifest, tmp_path)

    assert corpus[("axios", "0.21.1")] == {"lock:a", "lock:b"}
    assert corpus[("follow-redirects", "1.13.1")] == {"lock:a"}
    assert versions_by_name(corpus)["axios"] == {"0.21.1"}
