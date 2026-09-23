from entitygraph_rag.npm.dependencies import (
    build_edges,
    parent_dir,
    registry_only_declarations,
    resolve_dependencies,
    resolve_install_path,
    split_alias,
)
from entitygraph_rag.npm.lockfile import installed_packages
from entitygraph_rag.npm.registry import declared_dependencies

# app -> lib (^1) resolves to a nested lib@1 under app; the hoisted lib@2 is
# what everyone else gets. tool is installed twice and resolves `util`
# differently at each path.
LOCK = {
    "lockfileVersion": 3,
    "packages": {
        "": {"name": "depgraph-scratch", "dependencies": {"app": "1.0.0"}},
        "node_modules/app": {
            "version": "1.0.0",
            "dependencies": {"lib": "^1.0.0", "tool": "^3.0.0", "sw-cjs": "npm:string-width@^4.2.0"},
            "optionalDependencies": {"fsevents": "^2.0.0"},
            "peerDependencies": {"react": "^17", "canvas": "^2"},
            "peerDependenciesMeta": {"canvas": {"optional": True}},
        },
        "node_modules/app/node_modules/lib": {"version": "1.4.0"},
        "node_modules/lib": {"version": "2.0.0"},
        "node_modules/fsevents": {"version": "2.3.1", "optional": True},
        "node_modules/sw-cjs": {"name": "string-width", "version": "4.2.3"},
        "node_modules/tool": {"version": "3.0.0", "dependencies": {"util": "^1.0.0", "lib": "^2.0.0"}},
        "node_modules/util": {"version": "1.1.0"},
        "node_modules/other": {"version": "1.0.0", "dependencies": {"tool": "^3.0.0"}},
        "node_modules/other/node_modules/tool": {"version": "3.0.0", "dependencies": {"util": "^1.0.0", "lib": "^2.0.0"}},
        "node_modules/other/node_modules/util": {"version": "1.2.0"},
        "node_modules/deep": {"version": "1.0.0", "dependencies": {"lib": "^2.0.0"}},
        "node_modules/deep/node_modules/@s/inner": {"version": "1.0.0", "dependencies": {"lib": "*", "util": "*"}},
        "node_modules/deep/node_modules/@s/inner/node_modules/util": {"version": "0.9.0"},
    },
}


def deps_by_key():
    return {(d.source.path, d.dep_name): d for d in resolve_dependencies(LOCK)}


def test_parent_dir_handles_scopes_and_top_level():
    assert parent_dir("node_modules/a/node_modules/@s/b") == "node_modules/a"
    assert parent_dir("node_modules/a") == ""


def test_resolve_prefers_own_node_modules_then_walks_up():
    packages = LOCK["packages"]
    assert resolve_install_path("node_modules/app", "lib", packages) == "node_modules/app/node_modules/lib"
    assert resolve_install_path("node_modules/tool", "lib", packages) == "node_modules/lib"
    # From a nested scoped package: own dir, then deep's node_modules, then the top.
    assert resolve_install_path("node_modules/deep/node_modules/@s/inner", "util", packages) == (
        "node_modules/deep/node_modules/@s/inner/node_modules/util"
    )
    assert resolve_install_path("node_modules/deep/node_modules/@s/inner", "lib", packages) == "node_modules/lib"
    assert resolve_install_path("node_modules/app", "missing", packages) is None


def test_resolve_dependencies_keeps_type_range_and_alias_target():
    deps = deps_by_key()

    lib = deps[("node_modules/app", "lib")]
    assert (lib.target.version, lib.spec, lib.dependency_type) == ("1.4.0", "^1.0.0", "prod")
    assert deps[("node_modules/app", "fsevents")].dependency_type == "optional"
    alias = deps[("node_modules/app", "sw-cjs")]
    assert (alias.target.name, alias.target.version) == ("string-width", "4.2.3")
    assert ("", "app") not in deps  # the scratch root is not a package


def test_uninstalled_peers_are_unresolved_and_flag_optional_meta():
    deps = deps_by_key()

    react, canvas = deps[("node_modules/app", "react")], deps[("node_modules/app", "canvas")]
    assert react.target is None and not react.peer_optional
    assert canvas.target is None and canvas.peer_optional


def test_split_alias():
    assert split_alias("npm:string-width@^4.2.0") == "^4.2.0"
    assert split_alias("npm:@scope/pkg@~1.0.0") == "~1.0.0"
    assert split_alias("^1.0.0") == "^1.0.0"


def registry_lookup(overrides=None):
    """Registry metadata that mirrors the lockfile unless overridden."""
    by_nv = {(p.name, p.version): p for p in installed_packages(LOCK)}
    overrides = overrides or {}

    def lookup(name, version):
        if (name, version) in overrides:
            return overrides[(name, version)]
        pkg = by_nv.get((name, version))
        if pkg is None:
            return None
        # The registry repeats optional deps under `dependencies`.
        return {
            "dependencies": {**pkg.dependencies, **pkg.optional_dependencies},
            "optionalDependencies": pkg.optional_dependencies,
            "peerDependencies": pkg.peer_dependencies,
        }

    return lookup


def test_declared_dependencies_moves_optional_out_of_prod():
    split = declared_dependencies({"dependencies": {"a": "1", "f": "2"}, "optionalDependencies": {"f": "2"}})
    assert split == {"prod": {"a": "1"}, "optional": {"f": "2"}, "peer": {}}


def test_build_edges_merges_duplicates_and_keeps_split_resolutions():
    edges, unresolved = build_edges({"lock:a": resolve_dependencies(LOCK)}, registry_lookup())
    by_key = {(e["from_name"], e["dep_name"], e["to_version"]): e for e in edges}

    # tool@3.0.0 is installed twice; its `lib` dep resolves to lib@2.0.0 at both paths -> one edge.
    tool_lib = by_key[("tool", "lib", "2.0.0")]
    assert len(tool_lib["occurrences"]) == 2 and tool_lib["lockfile_doc_ids"] == ["lock:a"]
    # ...but its `util` dep resolves to different versions at each path -> two edges.
    assert {k[2] for k in by_key if k[:2] == ("tool", "util")} == {"1.1.0", "1.2.0"}

    alias = by_key[("app", "sw-cjs", "4.2.3")]
    assert (alias["to_name"], alias["version_range"], alias["declared_spec"]) == (
        "string-width", "^4.2.0", "npm:string-width@^4.2.0")
    assert {e["registry_check"] for e in edges} == {"match"}
    assert {(u["dep_name"], u["peer_optional"]) for u in unresolved} == {("react", False), ("canvas", True)}


def test_build_edges_lists_every_lockfile_an_edge_occurs_in():
    deps = resolve_dependencies(LOCK)
    edges, _ = build_edges({"lock:a": deps, "lock:b": deps}, registry_lookup())

    assert all(e["lockfile_doc_ids"] == ["lock:a", "lock:b"] for e in edges)


def test_registry_check_statuses():
    overrides = {
        ("app", "1.0.0"): {
            "dependencies": {"lib": "^1.1.0", "fsevents": "^2.0.0", "tool": "^3.0.0", "extra": "^1"},
            "optionalDependencies": {"fsevents": "^2.0.0"},
            "peerDependencies": {"sw-cjs": "npm:string-width@^4.2.0"},
        },
        ("util", "1.1.0"): {"missing": True},
    }
    lookup = registry_lookup(overrides)
    edges, _ = build_edges({"lock:a": resolve_dependencies(LOCK)}, lookup)
    status = {(e["from_name"], e["dep_name"], e["to_version"]): e["registry_check"] for e in edges}

    assert status[("app", "lib", "1.4.0")] == "range_differs"
    assert status[("app", "fsevents", "2.3.1")] == "match"
    assert status[("app", "sw-cjs", "4.2.3")] == "type_differs"
    assert status[("app", "tool", "3.0.0")] == "match"
    assert status[("other", "tool", "3.0.0")] == "match"

    app = next(p for p in installed_packages(LOCK) if p.name == "app")
    assert registry_only_declarations([app], lookup) == [
        {"name": "app", "version": "1.0.0", "dep_name": "extra", "dependency_type": "prod", "registry_spec": "^1"}
    ]


def test_registry_check_without_registry_data():
    edges, _ = build_edges({"lock:a": resolve_dependencies(LOCK)}, lambda name, version: None)
    assert {e["registry_check"] for e in edges} == {"no_registry_data"}
