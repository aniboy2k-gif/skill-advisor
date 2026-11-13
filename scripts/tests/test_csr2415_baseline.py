"""CSR #2415 — baseline comparison (B) + apply guards + reference integrity + pip major bump.

Design: ~/.claude/evidence/csr2415/da/r3-reflected.txt (R4-R6, R9, V1-V8) + r4-decisions.md (H1-H3, M1, M2).
Every network and git-remote call is faked; git repositories are real temp repositories.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import update  # noqa: E402
from channels import github_raw, pip as pip_channel  # noqa: E402

URL = "https://raw.githubusercontent.com/org/repo/main/skills/foo/SKILL.md"
C0, C1, C2 = "a" * 40, "b" * 40, "c" * 40
U0 = "---\nname: foo\ndescription: d\n---\n\n# Foo\n\nbody v0\n"
U1 = "---\nname: foo\ndescription: d\n---\n\n# Foo\n\nbody v1\n"
U2 = "---\nname: foo\ndescription: d\n---\n\n# Foo\n\nbody v2\n"
TC = "<!--trigger_conditions\nschema_version: \"0.1\"\n-->"


def pinned(c):
    return URL.replace("/main/", f"/{c}/")


def nh(text):
    return "sha256:" + hashlib.sha256(github_raw.normalize(text).encode("utf-8")).hexdigest()


def rh(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def with_tc(text):
    return github_raw.reinsert_trigger_conditions(text, TC)


def _env():
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    e.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
             GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    return e


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True, env=_env()).stdout.strip()


class Net:
    """fake raw host + fake git ls-remote."""

    def __init__(self):
        self.pages = {}
        self.head = C1
        self.calls = 0
        self.ls_fail = False

    def fetch(self, url):
        self.calls += 1
        v = self.pages.get(url)
        return v() if callable(v) else v

    def ls(self, org, repo, branch):
        self.calls += 1
        return None if self.ls_fail else self.head


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in list(os.environ):
        if k.startswith("GIT_"):
            monkeypatch.delenv(k)
    op = tmp_path / "op"
    (op / "skills" / "foo").mkdir(parents=True)
    (op / "vendor-patches").mkdir()
    (op / "vendor-patches" / "csr1-upstream-files.txt").write_text("# base: x\nskills/other/SKILL.md\n")
    (op / "skills" / "foo" / "SKILL.md").write_text(with_tc(U0))
    git(op, "init", "-q", "-b", "main")
    git(op, "add", "-A")
    git(op, "commit", "-qm", "init")
    wt = tmp_path / "wt"
    git(op, "worktree", "add", "-q", "-b", "wt", str(wt))
    net = Net()
    net.pages = {URL: U1, pinned(C0): U0, pinned(C1): U1}
    monkeypatch.setattr(github_raw, "fetch_upstream", net.fetch)
    monkeypatch.setattr(github_raw, "ls_remote", net.ls)
    monkeypatch.setattr(update, "op_root", lambda: op.resolve())
    sources = tmp_path / "skill-sources.json"
    monkeypatch.setattr(update, "SOURCES_PATH", sources)
    monkeypatch.setattr(update, "LOCK_PATH", tmp_path / "skill-sources.json.lock")
    entry = {"upstream_type": "community", "upstream_url": URL,
             "local_path": str(op / "skills" / "foo" / "SKILL.md")}

    class E:
        pass

    e = E()
    e.op, e.wt, e.net, e.sources, e.entry, e.tmp = op, wt, net, sources, entry, tmp_path
    e.local = op / "skills" / "foo" / "SKILL.md"
    e.wt_local = wt / "skills" / "foo" / "SKILL.md"

    def write_sources(**extra):
        ent = {**entry, **extra}
        sources.write_text(json.dumps({"schema_version": "1.0", "skills": {"foo": ent}}))
        return ent

    e.write_sources = write_sources
    e.load = lambda: json.loads(sources.read_text())["skills"]["foo"]
    return e


def base_obj(text, local_text, ref=C0):
    return {"sha256": nh(text), "ref": ref, "recorded_at": "2026-11-13T00:00:00+00:00",
            "note": "t", "local_sha256": nh(local_text)}


def run_main(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["update.py", *argv])
    rc = update.main()
    return rc, capsys.readouterr().out


# ─── R4 normalize ───────────────────────────────────────────────────────────

def test_normalize_matches_resync_function_body():
    text = "---\nname: x\n---\n\n" + TC + "\n\n# T\n"
    assert github_raw.normalize(text) == "---\nname: x\n---\n\n# T"
    assert github_raw.normalize(with_tc(U0)) == github_raw.normalize(U0)


def test_blank_line_false_positive_gone(env):
    """C-1 #2(1): compose layout (blank line before the block) was reported changed forever."""
    env.net.pages[URL] = U0
    r = github_raw.check("foo", env.entry, env.local, op_root=env.op)
    assert r["status"] == "up-to-date"


# ─── V1 baseline comparison ─────────────────────────────────────────────────

def test_v1_upstream_unchanged_local_modified_is_up_to_date(env):
    lm = U0 + "local edit\n"
    env.local.write_text(lm)
    env.net.pages[URL] = U0
    ent = {**env.entry, "baseline": base_obj(U0, lm)}
    r = github_raw.check("foo", ent, env.local, op_root=env.op)
    assert (r["status"], r["baseline_state"], r["local_state"]) == ("up-to-date", "matched", "local-modified")


def test_v1_upstream_changed_reports_counts(env):
    ent = {**env.entry, "baseline": base_obj(U0, with_tc(U0))}
    r = github_raw.check("foo", ent, env.local, op_root=env.op)
    assert (r["status"], r["baseline_state"]) == ("update-available", "upstream-changed")
    assert r["changed_lines"] == {"added": 1, "removed": 1}
    assert "diff_lines_added" not in r


def test_v1_no_baseline_old_behaviour(env):
    r = github_raw.check("foo", env.entry, env.local, op_root=env.op)
    assert r["status"] == "update-available"
    assert r["diff_basis"].startswith("local-vs-upstream")


def test_v1_raw_and_normalized_hash_kinds(env):
    env.net.pages[URL] = U0
    r = github_raw.check("foo", env.entry, env.local, op_root=env.op)
    assert r["upstream_hash"] == rh(U0)
    assert r["upstream_norm_hash"] == nh(U0)
    assert r["upstream_hash"] != r["upstream_norm_hash"]
    assert r["local_norm_hash"] == nh(with_tc(U0))


def test_v1c_unverifiable_baseline_text(env):
    env.net.pages[pinned(C0)] = U2
    ent = {**env.entry, "baseline": base_obj(U0, with_tc(U0))}
    r = github_raw.check("foo", ent, env.local, op_root=env.op)
    assert r["baseline_content"] == "unverifiable"
    assert r["changed_lines"] is None


def test_v1b_patch_status_three_valued(env, tmp_path):
    r = github_raw.check("foo", env.entry, env.local, op_root=env.op)
    assert r["patched"] is False
    (env.op / "vendor-patches" / "csr1-upstream-files.txt").write_text("# c\nskills/foo/SKILL.md\n")
    r = github_raw.check("foo", env.entry, env.local, op_root=env.op)
    assert r["patched"] is True and r["patch_sets"] == ["csr1"]
    r = github_raw.check("foo", env.entry, env.local, op_root=tmp_path / "nowhere")
    assert r["patched"] is None and r["patch_info"].startswith("unavailable")


# ─── V2 apply ───────────────────────────────────────────────────────────────

def _apply(env, ent, target=None, **kw):
    chk = github_raw.check("foo", ent, env.local, op_root=env.op)
    return chk, github_raw.apply("foo", ent, target or env.wt_local, chk, op_root=env.op, **kw)


def test_v2_lossless_apply_in_worktree_writes_pending_baseline(env):
    ent = env.write_sources(baseline=base_obj(U0, with_tc(U0)))
    _, res = _apply(env, ent)
    assert res["applied"] is True
    written = env.wt_local.read_text()
    assert TC in written and github_raw.normalize(written) == github_raw.normalize(U1)
    nb = res["new_baseline"]
    assert nb["sha256"] == nh(U1) and nb["ref"] == C1 and nb["local_sha256"] == nh(written)
    assert env.local.read_text() == with_tc(U0)


def test_v2_patched_refused_even_with_baseline_and_all_overrides(env):
    (env.op / "vendor-patches" / "csr1-upstream-files.txt").write_text("skills/foo/SKILL.md\n")
    ent = {**env.entry, "baseline": base_obj(U0, with_tc(U0))}
    _, res = _apply(env, ent, force_overwrite=True, allow_main=True, allow_missing_refs=True)
    assert res["blocked"] and "resync-skill.sh" in res["reason"]
    assert env.wt_local.read_text() == with_tc(U0)


def test_v2_patch_status_unavailable_refused(env):
    ent = {**env.entry, "baseline": base_obj(U0, with_tc(U0))}
    chk = github_raw.check("foo", ent, env.local, op_root=env.tmp / "nowhere")
    res = github_raw.apply("foo", ent, env.wt_local, chk, op_root=env.tmp / "nowhere")
    assert res["blocked"] and "unavailable" in res["reason"]


def test_v2_local_modified_with_baseline_refused_unless_force(env):
    lm = with_tc(U0) + "local edit\n"
    for p in (env.local, env.wt_local):
        p.write_text(lm)
    ent = {**env.entry, "baseline": base_obj(U0, lm)}
    _, res = _apply(env, ent)
    assert res["blocked"] and "local edit" in res["reason"]
    _, res = _apply(env, ent, force_overwrite=True)
    assert res["applied"] and Path(res["backup"]).exists()


def test_v2_operational_tree_refused_unless_allow_main(env):
    ent = {**env.entry, "baseline": base_obj(U0, with_tc(U0))}
    _, res = _apply(env, ent, target=env.local)
    assert res["blocked"] and "--allow-main" in res["reason"]
    _, res = _apply(env, ent, target=env.local, allow_main=True)
    assert res["applied"] and Path(res["backup"]).exists()


def test_v2g_submodule_skill_refused_without_override(env, tmp_path):
    sub_src = tmp_path / "subsrc"
    sub_src.mkdir()
    (sub_src / "SKILL.md").write_text(with_tc(U0))
    git(sub_src, "init", "-q", "-b", "main")
    git(sub_src, "add", "-A")
    git(sub_src, "commit", "-qm", "s")
    git(env.op, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub_src), "skills/subskill")
    git(env.op, "commit", "-qm", "sub")
    target = env.op / "skills" / "subskill" / "SKILL.md"
    git(target.parent, "checkout", "-q", "--detach")
    ent = {**env.entry, "local_path": str(target), "baseline": base_obj(U0, with_tc(U0))}
    chk = github_raw.check("subskill", ent, target, op_root=env.op)
    res = github_raw.apply("subskill", ent, target, chk, op_root=env.op,
                           allow_main=True, force_overwrite=True)
    assert res["blocked"] and "submodule" in res["reason"]
    assert target.read_text() == with_tc(U0)


def test_v2b_ref_binding_moved_upstream_refused(env):
    ent = {**env.entry, "baseline": base_obj(U0, with_tc(U0))}
    env.net.pages[pinned(C1)] = U2
    _, res = _apply(env, ent)
    assert res["blocked"] and "upstream moved since check" in res["reason"] and C1 in res["reason"]
    assert env.wt_local.read_text() == with_tc(U0)


def test_v2b_ls_remote_failure_applies_with_null_ref(env):
    env.net.ls_fail = True
    ent = {**env.entry, "baseline": base_obj(U0, with_tc(U0))}
    _, res = _apply(env, ent)
    assert res["applied"] and res["new_baseline"]["ref"] is None
    assert res["new_baseline"]["note"].startswith("apply; ref unresolved")


def test_v2b_ls_remote_failure_and_branch_moved_refused(env):
    env.net.ls_fail = True
    seq = iter([U1, U2])
    env.net.pages[URL] = lambda: next(seq)
    ent = {**env.entry, "baseline": base_obj(U0, with_tc(U0))}
    _, res = _apply(env, ent)
    assert res["blocked"] and "upstream moved since check" in res["reason"]
    assert env.wt_local.read_text() == with_tc(U0)


def test_v2b_non_raw_url_ref_null():
    assert github_raw.parse_raw_url("https://example.com/x/SKILL.md") is None
    assert github_raw.parse_raw_url(URL) == ("org", "repo", "main", "skills/foo/SKILL.md")


def test_v2c_no_baseline_guard(env):
    ent = env.write_sources()
    _, res = _apply(env, ent)
    assert res["blocked"] and "--set-baseline" in res["reason"]
    _, res = _apply(env, ent, force_overwrite=True)
    assert res["applied"] and "warning" in res


def test_v2d_divergence_reports_baseline_unconfirmed(env, monkeypatch, capsys):
    env.write_sources(baseline=base_obj(U1, with_tc(U0) + "x\n"))
    rc, out = run_main(monkeypatch, capsys, "foo", "--json")
    r = json.loads(out)["results"][0]
    assert r["status"] == "baseline-unconfirmed" and r["local_state"] == "changed-since-baseline"
    assert rc == 1


def test_v2e_local_changed_between_check_and_write_refused(env):
    ent = {**env.entry, "baseline": base_obj(U0, with_tc(U0))}
    chk = github_raw.check("foo", ent, env.local, op_root=env.op)
    env.wt_local.write_text(with_tc(U0) + "late edit\n")
    res = github_raw.apply("foo", ent, env.wt_local, chk, op_root=env.op)
    assert res["blocked"] and "local changed since check" in res["reason"]


def test_v2e_non_utf8_local_is_check_error_and_apply_refused(env):
    env.local.write_bytes(b"---\nname: foo\n---\n\xff\xfe\n")
    ent = {**env.entry, "baseline": base_obj(U0, with_tc(U0))}
    chk = github_raw.check("foo", ent, env.local, op_root=env.op)
    assert chk["status"] == "fetch-error" and "UTF-8" in chk["error"]
    res = github_raw.apply("foo", ent, env.wt_local, chk, op_root=env.op)
    assert res["blocked"]


def test_v2f_worktree_preconditions(env, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q", "-b", "main")
    git(other, "commit", "-q", "--allow-empty", "-m", "o")
    other_wt = tmp_path / "other_wt"
    git(other, "worktree", "add", "-q", "-b", "w", str(other_wt))
    for bad in (plain, env.op, other_wt):
        ok, why = update.validate_worktree(bad, env.op)
        assert not ok, bad
    assert update.validate_worktree(env.wt, env.op) == (True, "")


def test_v2f_invalid_worktree_refuses_before_any_fetch(env, monkeypatch, capsys):
    env.write_sources(baseline=base_obj(U0, with_tc(U0)))
    rc, out = run_main(monkeypatch, capsys, "foo", "--apply", "--yes", "--worktree", str(env.tmp))
    assert rc == 2 and env.net.calls == 0


def test_v2_apply_main_output_and_exit(env, monkeypatch, capsys):
    env.write_sources(baseline=base_obj(U0, with_tc(U0)))
    rc, out = run_main(monkeypatch, capsys, "foo", "--apply", "--yes", "--worktree", str(env.wt))
    assert rc == 0 and "[?]" not in out and "적용됨" in out
    saved = env.load()
    assert saved["pending_baseline"]["sha256"] == nh(U1)
    assert saved["baseline"]["sha256"] == nh(U0)


def test_v2h_abandoned_worktree_retry(env, monkeypatch, capsys):
    env.write_sources(baseline=base_obj(U0, with_tc(U0)))
    run_main(monkeypatch, capsys, "foo", "--apply", "--yes", "--worktree", str(env.wt))
    git(env.op, "worktree", "remove", "--force", str(env.wt))
    rc, out = run_main(monkeypatch, capsys, "foo", "--json")
    r = json.loads(out)["results"][0]
    assert (r["status"], r["baseline_state"]) == ("update-available", "upstream-changed") and rc == 1
    wt2 = env.tmp / "wt2"
    git(env.op, "worktree", "add", "-q", "-b", "wt2", str(wt2))
    rc, out = run_main(monkeypatch, capsys, "foo", "--apply", "--yes", "--worktree", str(wt2))
    assert rc == 0


def test_v2h_pending_promoted_after_merge(env, monkeypatch, capsys):
    env.write_sources(baseline=base_obj(U0, with_tc(U0)))
    run_main(monkeypatch, capsys, "foo", "--apply", "--yes", "--worktree", str(env.wt))
    env.local.write_text(env.wt_local.read_text())  # PR merged + operational pull
    rc, out = run_main(monkeypatch, capsys, "foo", "--json")
    r = json.loads(out)["results"][0]
    assert (r["status"], r["local_state"], r["baseline_source"]) == ("up-to-date", "same", "pending")
    rc, out = run_main(monkeypatch, capsys, "foo", "--set-baseline", "foo", "--hash", nh(U1), "--yes")
    saved = env.load()
    assert rc == 0 and "pending_baseline" not in saved and saved["baseline"]["sha256"] == nh(U1)


# ─── V3 --set-baseline ─────────────────────────────────────────────────────

def test_v3_set_baseline(env, monkeypatch, capsys):
    env.write_sources()
    before = env.sources.read_text()
    rc, out = run_main(monkeypatch, capsys, "--set-baseline", "foo", "--hash", nh(U0), "--yes")
    assert rc == 2 and env.sources.read_text() == before
    for extra in ([], ["--yes"]):
        rc, out = run_main(monkeypatch, capsys, "--set-baseline", "foo", *extra)
        assert rc == 0 and nh(U1) in out and env.sources.read_text() == before
    rc, out = run_main(monkeypatch, capsys, "--set-baseline", "foo", "--hash", nh(U1), "--yes")
    b = env.load()["baseline"]
    assert rc == 0 and b["sha256"] == nh(U1) and b["ref"] == C1 and b["local_sha256"] == nh(with_tc(U0))
    rc, _ = run_main(monkeypatch, capsys, "--set-baseline", "foo", "--hash", nh(U1), "--yes")
    assert rc == 0 and env.load()["baseline"]["sha256"] == nh(U1)


def test_v3_set_baseline_with_ref(env, monkeypatch, capsys):
    env.write_sources()
    rc, _ = run_main(monkeypatch, capsys, "--set-baseline", "foo", "--ref", C0, "--hash", nh(U0), "--yes")
    b = env.load()["baseline"]
    assert rc == 0 and (b["ref"], b["sha256"]) == (C0, nh(U0))


def test_v3_set_baseline_patched_prints_resync_note(env, monkeypatch, capsys):
    (env.op / "vendor-patches" / "csr1-upstream-files.txt").write_text("skills/foo/SKILL.md\n")
    env.write_sources()
    rc, out = run_main(monkeypatch, capsys, "--set-baseline", "foo", "--hash", nh(U1), "--yes")
    assert rc == 0 and "resync-skill.sh does not read or update this baseline" in out


def test_v3_save_preserves_other_skill_written_concurrently(env):
    env.write_sources()
    data = json.loads(env.sources.read_text())
    data["skills"]["bar"] = {"upstream_type": "local_custom"}
    env.sources.write_text(json.dumps(data))
    env.sources.chmod(0o600)
    update.save_skill_keys({"foo": {"status": "up-to-date"}})
    after = json.loads(env.sources.read_text())["skills"]
    assert "bar" in after and after["foo"]["status"] == "up-to-date"
    assert env.sources.stat().st_mode & 0o777 == 0o600


def test_v3b_concurrent_writers_both_survive(env, tmp_path):
    env.write_sources()
    script = tmp_path / "w.py"
    script.write_text(
        "import sys; sys.path.insert(0, %r)\n"
        "import update\nfrom pathlib import Path\n"
        "update.SOURCES_PATH = Path(%r); update.LOCK_PATH = Path(%r)\n"
        "for i in range(40): update.save_skill_keys({sys.argv[1]: {'n': i + 1}})\n"
        % (str(Path(update.__file__).parent), str(env.sources), str(tmp_path / "skill-sources.json.lock")))
    ps = [subprocess.Popen([sys.executable, str(script), name]) for name in ("s1", "s2")]
    assert all(p.wait() == 0 for p in ps)
    after = json.loads(env.sources.read_text())["skills"]
    assert after["s1"]["n"] == 40 and after["s2"]["n"] == 40 and "foo" in after


# ─── V4 reference integrity ────────────────────────────────────────────────

def test_v4_missing_refs(tmp_path):
    root = tmp_path / "skills"
    (root / "foo" / "references").mkdir(parents=True)
    (root / "foo" / "references" / "a.md").write_text("x")
    (root / "using-superpowers" / "references").mkdir(parents=True)
    text = ("see [x](../using-superpowers/references/codex-tools.md) and "
            "`~/.claude/scripts/hooks/suggest-compact.js` and `reference/a.md` "
            "and [u](https://example.com/z.md) and `scripts/merge_runs.py`")
    miss = github_raw.missing_refs(text, root / "foo", root)
    assert miss == ["../using-superpowers/references/codex-tools.md", "scripts/merge_runs.py"]
    (root / "using-superpowers" / "references" / "codex-tools.md").write_text("x")
    assert github_raw.missing_refs(text, root / "foo", root) == ["scripts/merge_runs.py"]


def test_v4_new_missing_refs_block_apply(env):
    env.net.pages[URL] = U1 + "\nrun `scripts/new_tool.py`\n"
    env.net.pages[pinned(C1)] = env.net.pages[URL]
    ent = {**env.entry, "baseline": base_obj(U0, with_tc(U0))}
    chk, res = _apply(env, ent)
    assert chk["new_missing_refs"] == ["scripts/new_tool.py"]
    assert res["blocked"] and "scripts/new_tool.py" in res["reason"]
    _, res = _apply(env, ent, allow_missing_refs=True)
    assert res["applied"]


def test_v4b_refs_checked_against_write_target(env):
    env.net.pages[URL] = U1 + "\nrun `scripts/tool.py`\n"
    env.net.pages[pinned(C1)] = env.net.pages[URL]
    (env.op / "skills" / "foo" / "scripts").mkdir()
    (env.op / "skills" / "foo" / "scripts" / "tool.py").write_text("x")
    ent = {**env.entry, "baseline": base_obj(U0, with_tc(U0))}
    chk, res = _apply(env, ent)
    assert chk["new_missing_refs"] == []
    assert res["blocked"] and "scripts/tool.py" in res["reason"]


# ─── run_apply merge (C-1 #9) · pip (C-1 #7) ───────────────────────────────

def test_run_apply_rows_replace_check_rows(env, monkeypatch, capsys):
    env.write_sources(baseline=base_obj(U0, with_tc(U0)))
    rc, out = run_main(monkeypatch, capsys, "foo", "--apply", "--yes", "--worktree", str(env.wt), "--json")
    rows = json.loads(out)["results"]
    assert len(rows) == 1 and rows[0]["status"] == "up-to-date" and rows[0]["applied"] is True
    assert rc == 0


def test_pip_major_bump(monkeypatch):
    out = json.dumps([{"name": "anthropic", "version": "0.109.0", "latest_version": "2.0.1"},
                      {"name": "requests", "version": "2.31.0", "latest_version": "2.32.0"}])
    monkeypatch.setattr(pip_channel, "_run", lambda cmd: (0, out, ""))
    r = pip_channel.check("s", {"type_specific_metadata": {"pip_packages": ["anthropic", "requests"]}}, Path("."))
    assert r["outdated"]["anthropic"]["major_bump"] is True
    assert r["outdated"]["requests"]["major_bump"] is False
    assert "anthropic 0.109.0->2.0.1" in r["warning"]
