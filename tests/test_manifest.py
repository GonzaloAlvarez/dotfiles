import pytest
import yaml

from seshatlib import manifest
from seshatlib.manifest import Facts, ManifestError


def write_bundle(repo, name, doc):
    if name == "default":
        path = repo / "bundles" / "default.yml"
    else:
        path = repo / "bundles" / name / "bundle.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc))
    return path


def default_doc(targets=None, **extra):
    doc = {"schema": 1, "name": "default", "automatic": True, "targets": targets or []}
    doc.update(extra)
    return doc


def copy_target(tid="app.conf", source="payload/conf", dest="~/.conf", **extra):
    t = {"id": tid, "operation": "copy", "source": source, "destination": dest}
    t.update(extra)
    return t


def test_minimal_default_loads(work_repo):
    write_bundle(work_repo, "default", default_doc([copy_target()]))
    bundles = manifest.load_bundles(work_repo)
    assert bundles["default"].automatic
    assert bundles["default"].targets[0].operation == "copy"


def test_missing_default_rejected(work_repo):
    (work_repo / "bundles").mkdir()
    with pytest.raises(ManifestError):
        manifest.load_bundles(work_repo)


def test_unknown_bundle_field_rejected(work_repo):
    write_bundle(work_repo, "default", default_doc([], surprise=1))
    with pytest.raises(ManifestError, match="unknown fields"):
        manifest.load_bundles(work_repo)


def test_unknown_target_field_rejected(work_repo):
    t = copy_target()
    t["shazam"] = True
    write_bundle(work_repo, "default", default_doc([t]))
    with pytest.raises(ManifestError, match="unknown fields"):
        manifest.load_bundles(work_repo)


@pytest.mark.parametrize("bad", ["../bundle", "llm..claude", "/absolute", "LLM.Claude", "bundle/name", "9lives"])
def test_invalid_bundle_ids(work_repo, bad):
    write_bundle(work_repo, "default", {"schema": 1, "name": bad, "targets": []})
    with pytest.raises(ManifestError):
        manifest.load_bundles(work_repo)


def test_bundle_name_must_match_directory(work_repo):
    write_bundle(work_repo, "default", default_doc())
    write_bundle(work_repo, "llm.claude", {"schema": 1, "name": "other.name", "targets": []})
    with pytest.raises(ManifestError, match="does not match"):
        manifest.load_bundles(work_repo)


def test_duplicate_target_ids_within_bundle(work_repo):
    write_bundle(work_repo, "default", default_doc([copy_target(), copy_target(dest="~/.conf2")]))
    with pytest.raises(ManifestError, match="duplicate target id"):
        manifest.load_bundles(work_repo)


def test_duplicate_target_ids_across_bundles(work_repo):
    write_bundle(work_repo, "default", default_doc([copy_target()]))
    write_bundle(
        work_repo,
        "extra",
        {"schema": 1, "name": "extra", "targets": [copy_target(dest="~/.conf2")]},
    )
    with pytest.raises(ManifestError, match="declared by both"):
        manifest.load_bundles(work_repo)


def test_dependency_cycle_rejected(work_repo):
    write_bundle(work_repo, "default", default_doc())
    write_bundle(work_repo, "a", {"schema": 1, "name": "a", "depends_on": ["b"], "targets": []})
    write_bundle(work_repo, "b", {"schema": 1, "name": "b", "depends_on": ["a"], "targets": []})
    with pytest.raises(ManifestError, match="cycle"):
        manifest.load_bundles(work_repo)


def test_missing_dependency_rejected(work_repo):
    write_bundle(work_repo, "default", default_doc())
    write_bundle(work_repo, "a", {"schema": 1, "name": "a", "depends_on": ["ghost"], "targets": []})
    with pytest.raises(ManifestError, match="unknown bundle"):
        manifest.load_bundles(work_repo)


def test_unsupported_operation_rejected(work_repo):
    t = {"id": "x.y", "operation": "teleport", "source": "a", "destination": "~/.x"}
    write_bundle(work_repo, "default", default_doc([t]))
    with pytest.raises(ManifestError, match="unsupported operation"):
        manifest.load_bundles(work_repo)


def test_unknown_when_fact_rejected(work_repo):
    t = copy_target(when={"planet": ["mars"]})
    write_bundle(work_repo, "default", default_doc([t]))
    with pytest.raises(ManifestError, match="unknown fact"):
        manifest.load_bundles(work_repo)


def test_owns_must_be_top_level(work_repo):
    t = {
        "id": "j.m",
        "operation": "json_merge",
        "source": "frag.json",
        "destination": "~/.s.json",
        "owns": ["/env/AWS_PROFILE"],
    }
    write_bundle(work_repo, "default", default_doc([t]))
    with pytest.raises(ManifestError, match="owns"):
        manifest.load_bundles(work_repo)


def test_json_merge_requires_owns(work_repo):
    t = {"id": "j.m", "operation": "json_merge", "source": "frag.json", "destination": "~/.s.json"}
    write_bundle(work_repo, "default", default_doc([t]))
    with pytest.raises(ManifestError, match="requires owns"):
        manifest.load_bundles(work_repo)


def test_replaces_only_default(work_repo):
    t = copy_target(replaces=["other.bundle"])
    write_bundle(work_repo, "default", default_doc([t]))
    with pytest.raises(ManifestError, match="replaces"):
        manifest.load_bundles(work_repo)


def test_git_tree_field_rules(work_repo):
    t = {"id": "g.t", "operation": "git_tree", "destination": "~/.vim"}
    write_bundle(work_repo, "default", default_doc([t]))
    with pytest.raises(ManifestError, match="git_tree requires url"):
        manifest.load_bundles(work_repo)


def test_link_requires_target(work_repo):
    t = {"id": "l.t", "operation": "link", "destination": "~/.bash_profile"}
    write_bundle(work_repo, "default", default_doc([t]))
    with pytest.raises(ManifestError, match="link requires target"):
        manifest.load_bundles(work_repo)


def test_mode_validation(work_repo):
    write_bundle(work_repo, "default", default_doc([copy_target(mode="755")]))
    with pytest.raises(ManifestError, match="mode"):
        manifest.load_bundles(work_repo)
    write_bundle(work_repo, "default", default_doc([copy_target(mode="0755")]))
    bundles = manifest.load_bundles(work_repo)
    assert bundles["default"].targets[0].mode == 0o755


def test_variants_first_match_wins(work_repo, facts):
    t = {
        "id": "aider.conf",
        "operation": "copy",
        "destination": "~/.aider.conf.yml",
        "variants": [
            {"when": {"user": ["galvarez"]}, "source": "aider/openai.yml"},
            {"source": "aider/base.yml"},
        ],
    }
    write_bundle(work_repo, "default", default_doc([t]))
    bundles = manifest.load_bundles(work_repo)
    rt = manifest.resolve_targets(bundles["default"], facts)[0]
    assert rt.source == "aider/openai.yml"
    other = Facts(os="linux", arch="amd64", user="nobody", hostname="x")
    rt = manifest.resolve_targets(bundles["default"], other)[0]
    assert rt.source == "aider/base.yml"


def test_variant_no_match_deactivates_target(work_repo):
    t = {
        "id": "x.y",
        "operation": "copy",
        "destination": "~/.x",
        "variants": [{"when": {"user": ["someoneelse"]}, "source": "a"}],
    }
    write_bundle(work_repo, "default", default_doc([t]))
    bundles = manifest.load_bundles(work_repo)
    f = Facts(os="darwin", arch="arm64", user="galvarez", hostname="h")
    assert manifest.resolve_targets(bundles["default"], f) == []


def test_when_filters_targets(work_repo, facts):
    t1 = copy_target("mac.only", dest="~/.mac", when={"os": ["darwin"]})
    t2 = copy_target("linux.only", dest="~/.linux", when={"os": ["linux"]})
    write_bundle(work_repo, "default", default_doc([t1, t2]))
    bundles = manifest.load_bundles(work_repo)
    ids = [rt.id for rt in manifest.resolve_targets(bundles["default"], facts)]
    assert ids == ["mac.only"]


def test_platform_gates_bundle(work_repo, facts):
    write_bundle(work_repo, "default", default_doc([copy_target()], platforms={"os": ["linux"]}))
    bundles = manifest.load_bundles(work_repo)
    assert manifest.resolve_targets(bundles["default"], facts) == []


def test_overlap_two_bundles_one_file(work_repo, facts):
    write_bundle(work_repo, "default", default_doc([copy_target()]))
    write_bundle(
        work_repo,
        "extra",
        {"schema": 1, "name": "extra", "targets": [copy_target(tid="other.conf")]},
    )
    bundles = manifest.load_bundles(work_repo)
    with pytest.raises(ManifestError, match="claimed by both"):
        manifest.check_overlaps(bundles, facts)


def test_overlap_allowed_with_replaces(work_repo, facts):
    write_bundle(work_repo, "default", default_doc([copy_target()]))
    write_bundle(
        work_repo,
        "extra",
        {
            "schema": 1,
            "name": "extra",
            "targets": [copy_target(tid="other.conf", source="alt/conf", replaces=["default"])],
        },
    )
    bundles = manifest.load_bundles(work_repo)
    manifest.check_overlaps(bundles, facts)


def test_overlap_json_key_conflict(work_repo, facts):
    j1 = {
        "id": "a.j",
        "operation": "json_merge",
        "source": "a.json",
        "destination": "~/.s.json",
        "owns": ["/env"],
    }
    j2 = {
        "id": "b.j",
        "operation": "json_merge",
        "source": "b.json",
        "destination": "~/.s.json",
        "owns": ["/env"],
    }
    write_bundle(work_repo, "default", default_doc([j1]))
    write_bundle(work_repo, "extra", {"schema": 1, "name": "extra", "targets": [j2]})
    bundles = manifest.load_bundles(work_repo)
    with pytest.raises(ManifestError, match="owned by both"):
        manifest.check_overlaps(bundles, facts)


def test_overlap_json_keys_disjoint_ok(work_repo, facts):
    j1 = {
        "id": "a.j",
        "operation": "json_merge",
        "source": "a.json",
        "destination": "~/.s.json",
        "owns": ["/statusLine"],
    }
    j2 = {
        "id": "b.j",
        "operation": "json_merge",
        "source": "b.json",
        "destination": "~/.s.json",
        "owns": ["/env"],
    }
    write_bundle(work_repo, "default", default_doc([j1]))
    write_bundle(work_repo, "extra", {"schema": 1, "name": "extra", "targets": [j2]})
    bundles = manifest.load_bundles(work_repo)
    manifest.check_overlaps(bundles, facts)


def test_overlap_git_tree_descendant(work_repo, facts):
    g = {"id": "nvim.tree", "operation": "git_tree", "url": "https://x/y", "destination": "~/.config/nvim"}
    c = copy_target("nvim.init", dest="~/.config/nvim/init.lua")
    write_bundle(work_repo, "default", default_doc([g, c]))
    bundles = manifest.load_bundles(work_repo)
    with pytest.raises(ManifestError, match="overlaps directory"):
        manifest.check_overlaps(bundles, facts)


def test_digest_changes_with_payload(work_repo, facts):
    (work_repo / "payload").mkdir()
    (work_repo / "payload" / "conf").write_text("v1\n")
    write_bundle(work_repo, "default", default_doc([copy_target()]))
    bundles = manifest.load_bundles(work_repo)
    d1 = manifest.bundle_source_digest(bundles["default"], work_repo, facts)
    d1_again = manifest.bundle_source_digest(bundles["default"], work_repo, facts)
    assert d1 == d1_again
    (work_repo / "payload" / "conf").write_text("v2\n")
    d2 = manifest.bundle_source_digest(bundles["default"], work_repo, facts)
    assert d1 != d2


def test_digest_ignores_unrelated_files(work_repo, facts):
    (work_repo / "payload").mkdir()
    (work_repo / "payload" / "conf").write_text("v1\n")
    write_bundle(work_repo, "default", default_doc([copy_target()]))
    bundles = manifest.load_bundles(work_repo)
    d1 = manifest.bundle_source_digest(bundles["default"], work_repo, facts)
    (work_repo / "unrelated.txt").write_text("noise\n")
    d2 = manifest.bundle_source_digest(bundles["default"], work_repo, facts)
    assert d1 == d2


def test_digest_ignores_inactive_targets(work_repo, facts):
    (work_repo / "payload").mkdir()
    (work_repo / "payload" / "conf").write_text("v1\n")
    (work_repo / "payload" / "linuxconf").write_text("l1\n")
    targets = [
        copy_target(),
        copy_target("linux.conf", source="payload/linuxconf", dest="~/.lc", when={"os": ["linux"]}),
    ]
    write_bundle(work_repo, "default", default_doc(targets))
    bundles = manifest.load_bundles(work_repo)
    d1 = manifest.bundle_source_digest(bundles["default"], work_repo, facts)
    (work_repo / "payload" / "linuxconf").write_text("l2\n")
    d2 = manifest.bundle_source_digest(bundles["default"], work_repo, facts)
    assert d1 == d2


def test_digest_missing_source_errors(work_repo, facts):
    write_bundle(work_repo, "default", default_doc([copy_target()]))
    bundles = manifest.load_bundles(work_repo)
    with pytest.raises(ManifestError, match="source not found"):
        manifest.bundle_source_digest(bundles["default"], work_repo, facts)


def test_resolve_order(work_repo):
    write_bundle(work_repo, "default", default_doc())
    write_bundle(work_repo, "mid", {"schema": 1, "name": "mid", "depends_on": ["default"], "targets": []})
    write_bundle(work_repo, "top", {"schema": 1, "name": "top", "depends_on": ["mid"], "targets": []})
    bundles = manifest.load_bundles(work_repo)
    assert manifest.resolve_order(bundles, "top") == ["default", "mid", "top"]


def test_variable_validation(work_repo):
    doc = default_doc()
    doc["variables"] = {"aws_region": {"type": "integer", "default": "x"}}
    write_bundle(work_repo, "default", doc)
    with pytest.raises(ManifestError, match="only type string"):
        manifest.load_bundles(work_repo)


def test_kauket_requires_validation(work_repo):
    doc = default_doc()
    doc["requires"] = {"kauket": [{"id": "aws.profile.bedrock", "action": "delete"}]}
    write_bundle(work_repo, "default", doc)
    with pytest.raises(ManifestError, match="kauket action"):
        manifest.load_bundles(work_repo)
