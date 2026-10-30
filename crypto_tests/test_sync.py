"""Real Git merge tests without network or credentials."""
import pytest
from scripts.crypto_sync import git, prepare_candidate


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Fixture")
    git(tmp_path, "config", "user.email", "fixture@localhost")
    git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "core.txt").write_text("baseline\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "baseline")
    git(tmp_path, "branch", "upstream")
    (tmp_path / "crypto.txt").write_text("extension\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "crypto extension")
    return tmp_path


def test_normal_sync_deterministic_and_checkout_untouched(repo):
    base = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "switch", "upstream")
    (repo / "core.txt").write_text("upstream update\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "official update")
    git(repo, "switch", "main")
    first = prepare_candidate(repo, "main", "upstream")
    assert first == prepare_candidate(repo, "main", "upstream") and first["status"] == "ready"
    sha = first["candidate_sha"]
    assert git(repo, "show", f"{sha}:core.txt").stdout == "upstream update\n"
    assert git(repo, "show", f"{sha}:crypto.txt").stdout == "extension\n"
    assert git(repo, "rev-parse", "HEAD").stdout.strip() == base
    assert (repo / "core.txt").read_text() == "baseline\n"
    assert not git(repo, "status", "--porcelain").stdout
    assert prepare_candidate(repo, sha, "upstream")["status"] == "unchanged"


def test_conflict_no_candidate_and_keeps_local_work(repo):
    (repo / "core.txt").write_text("local change\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "local core change")
    base = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "switch", "upstream")
    (repo / "core.txt").write_text("incompatible upstream\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "upstream core change")
    git(repo, "switch", "main")
    (repo / "uncommitted.txt").write_text("keep me")
    result = prepare_candidate(repo, "main", "upstream")
    assert result["status"] == "conflict" and result["candidate_sha"] is None
    assert "core.txt" in result["conflict_paths"] and not result["changed"]
    assert git(repo, "rev-parse", "HEAD").stdout.strip() == base
    assert (repo / "uncommitted.txt").read_text() == "keep me"
    assert not (repo / ".git/MERGE_HEAD").exists()


def test_already_synced_no_commit(repo):
    result = prepare_candidate(repo, "main", "upstream")
    assert result["status"] == "unchanged" and not result["changed"]


def test_bad_revision_fails(repo):
    import subprocess
    with pytest.raises(subprocess.CalledProcessError):
        prepare_candidate(repo, "main", "missing-ref")
