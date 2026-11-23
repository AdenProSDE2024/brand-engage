import urllib.request
from pathlib import Path

import pytest

from brand_engage.cli import _emit, _show_body, run
from brand_engage.config import repo_root
from brand_engage.draft import draft_problems
from brand_engage.models import Settings

ROOT = repo_root()


def _drafts(text: str) -> list[str]:
    found = []
    for block in text.split("\n---\n"):
        if "Draft:" not in block:
            continue
        draft = block.split("Draft:", 1)[1]
        draft = draft.split("Edit before posting:", 1)[0]
        found.append(draft.strip())
    return found


def test_dry_run_writes_a_phone_digest_without_touching_the_network(tmp_path, monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise AssertionError("network was called during dry-run")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    monkeypatch.setenv("X_BEARER_TOKEN", "super-secret-token")
    monkeypatch.setenv("LLM_API_KEY", "sk-super-secret")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T000/B000/secretvalue")

    out = tmp_path / "digest.md"
    log = tmp_path / "log.csv"
    code = run(["--dry-run", "--out", str(out), "--log", str(log)])
    captured = capsys.readouterr()
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert text == captured.out
    assert "super-secret" not in text
    assert "secretvalue" not in captured.err

    headings = [
        line
        for line in text.splitlines()
        if len(line) > 3 and line[0].isdigit() and line[1:3] == ". "
    ]
    assert 6 <= len(headings) <= 8
    assert headings[0].startswith("1. Reply on X")
    assert "https://x.com/swyx/status/1001" in text
    assert text.index("https://x.com/swyx/status/1001") < text.index("Comment on LinkedIn")
    assert "https://x.com/pmarca/status/1009" not in text
    assert "https://x.com/swyx/status/1008" not in text
    assert "https://x.com/small_ops_example/status/1010" not in text
    assert "Dry run. Made-up posts. Do not post these." in text
    assert "Do not cross-post" in text
    assert "Check these LinkedIn profiles" in text
    assert "TODO_pe_operating_partner" in text
    assert "never shown the job" in text
    assert "embarrassed to share" in text
    assert "which step was actually removed" in text
    assert "UNSCRIPTED FALLBACK" not in text
    assert "—" not in text
    assert "–" not in text

    for draft in _drafts(text):
        kind = "original" if "workshop" in draft or "clean files" in draft else "reply"
        assert draft_problems(draft, kind=kind) == [], draft

    log_text = log.read_text(encoding="utf-8")
    assert log_text.startswith("date,platform,kind,url,author,draft,used,result,notes")
    assert "https://x.com/swyx/status/1001" in log_text
    assert ",yes," not in log_text
    # The repo log is not the dry-run target.
    repo_log = (ROOT / "log.csv").read_text(encoding="utf-8")
    assert "swyx" not in repo_log


def test_live_run_requires_keys(monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert run([]) == 1


def test_actions_log_does_not_receive_draft_text(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    settings = Settings(commit_digest=False)
    _emit("SECRET DRAFT about the shadow environment", settings=settings, dry_run=False, out=tmp_path / "d.md")
    captured = capsys.readouterr()
    assert "SECRET DRAFT" not in captured.out
    assert "SECRET DRAFT" not in captured.err
    assert _show_body(settings, dry_run=False) is False
    assert _show_body(Settings(commit_digest=True), dry_run=False) is True
    assert _show_body(settings, dry_run=True) is True


def test_workflow_is_weekday_morning_pacific_and_cannot_push_by_default():
    daily = Path(ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    assert 'cron: "30 14 * * 1-5"' in daily
    assert "workflow_dispatch" in daily
    assert "contents: read" in daily
    assert daily.count("contents: write") == 1
    assert "commit_digest" in daily
    assert "X_BEARER_TOKEN" in daily
    assert "LLM_API_KEY" in daily
    assert "SLACK_WEBHOOK_URL" in daily
    ci = Path(ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pytest" in ci
    assert "contents: read" in ci
