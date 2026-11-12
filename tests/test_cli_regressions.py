"""CLI regressions from kali's review, grouped by the four owned work tranches.

These assert the intended behavior, not the faulty behavior observed during review.
All state and settings stay under tmp_path; race windows are scheduled without sleeps.
"""
import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from tokeneconomizer.plugin import cli, denylist, fold, hosts, repos
from tokeneconomizer.plugin.context import LiveContext


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    for key, value in {
        "TOKENECONOMIZER_HOME": str(tmp_path / "te"),
        "TE_FOLD_SYNC": "1",
        "TE_MICROSKILLS": "off",
        "TE_LOOPGUARD": "off",
        "TE_TOOLPRUNE": "auto",
        "TE_TOOLPRUNE_QUIET_MINUTES": "0",
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)
    for key in ("TOKENECONOMIZER_REPO", "TE_HOST"):
        monkeypatch.delenv(key, raising=False)
    work = tmp_path / "work"
    work.mkdir()
    context = LiveContext.build(hosts.ClaudeCode(), str(work))
    context.store.ensure()
    return context


def run(ctx, *args):
    return cli.main(["--host", ctx.host.name, "--cwd", ctx.repo.root, *args])


# T1 / kali: repo merge keys must not reach outside the repository-state directory.
@pytest.mark.parametrize("key_form", ["absolute", "traversal"])
def test_repos_merge_rejects_source_paths_without_moving_user_files(ctx, tmp_path, key_form):
    unrelated = tmp_path / "valuable-project"
    unrelated.mkdir()
    marker = unrelated / "important.txt"
    marker.write_text("not plugin state", encoding="utf-8")
    source = (str(unrelated) if key_form == "absolute"
              else os.path.join("..", "..", unrelated.name))

    result = run(ctx, "repos", "merge", source)

    assert unrelated.is_dir(), "merge must not rename a directory outside plugin state"
    assert marker.read_text(encoding="utf-8") == "not plugin state"
    assert not list(tmp_path.glob("valuable-project.*"))
    assert result == 2


@pytest.mark.parametrize("key_form", ["absolute", "traversal"])
def test_repos_merge_rejects_destination_paths_without_moving_state(ctx, tmp_path, key_form):
    source = Path(ctx.root) / "repos" / "orphan" / "claude" / "sessions" / "old.json"
    source.parent.mkdir(parents=True)
    session = {"session_id": "old", "host": "claude"}
    source.write_text(json.dumps(session), encoding="utf-8")
    outside = tmp_path / "outside"
    destination = (str(outside) if key_form == "absolute"
                   else os.path.join("..", "..", outside.name))

    result = run(ctx, "repos", "merge", "orphan", destination)

    assert not outside.exists(), "merge must not write outside the state root"
    assert json.loads(source.read_text(encoding="utf-8")) == session
    assert result == 2


# Fix hardening / miha: keys name one real state directory, never a path or alias.
@pytest.mark.parametrize("key", ["", ".", "..", "orphan/../orphan", r"orphan\..\orphan"])
@pytest.mark.parametrize("position", ["source", "destination"])
def test_repos_merge_rejects_non_directory_keys(ctx, key, position):
    source = Path(ctx.root) / "repos" / "orphan" / "claude" / "sessions" / "old.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"session_id": "old"}', encoding="utf-8")
    keys = [key, ctx.repo.key] if position == "source" else ["orphan", key]

    assert run(ctx, "repos", "merge", *keys) == 2
    assert source.read_text(encoding="utf-8") == '{"session_id": "old"}'


@pytest.mark.parametrize("position", ["source", "destination"])
def test_repos_merge_rejects_symlink_keys(ctx, tmp_path, position):
    source = Path(ctx.root) / "repos" / "orphan" / "claude" / "sessions" / "old.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"session_id": "old"}', encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "important.txt"
    marker.write_text("not plugin state", encoding="utf-8")
    link = Path(ctx.root) / "repos" / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    keys = ["linked", ctx.repo.key] if position == "source" else ["orphan", "linked"]

    assert run(ctx, "repos", "merge", *keys) == 2
    assert link.is_symlink()
    assert list(outside.iterdir()) == [marker]
    assert marker.read_text(encoding="utf-8") == "not plugin state"
    assert source.read_text(encoding="utf-8") == '{"session_id": "old"}'


# T2 / kali: restore and background apply must preserve ownership of every deny rule.
def test_restore_preserves_ownership_of_a_concurrent_background_apply(ctx, monkeypatch):
    assert denylist.apply(ctx.repo.root, ["CronCreate"], ctx.store) == ["CronCreate"]
    ctx.store.write("untool.json", {
        "proposal": ["Workflow"],
        "auto_pending": {"items": ["Workflow"], "root": ctx.repo.root, "since": 1},
    })
    read_settings = denylist._read_settings
    attempted = False
    applied = False

    def background_apply():
        nonlocal applied
        # If restore holds the worker's lock, schedule this writer after
        # restore rather than block the test thread. Release the probe lock
        # before running apply_pending, which acquires the lock itself.
        with ctx.store.locked("mechanisms", timeout=0) as acquired:
            pass
        if acquired:
            assert fold.apply_pending(ctx) is None
            applied = True

    def read_with_background_apply(path):
        nonlocal attempted
        # Restore has read its ownership snapshot by this point. Try the other
        # writer once; its own settings read must not recursively schedule it.
        if not attempted:
            attempted = True
            background_apply()
        return read_settings(path)

    with monkeypatch.context() as race:
        race.setattr(denylist, "_read_settings", read_with_background_apply)
        assert run(ctx, "toolprune", "restore", "CronCreate") == 0
    assert attempted
    if not applied:
        background_apply()
    assert applied

    settings_path = Path(denylist.settings_path(ctx.repo.root))
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["permissions"]["deny"] == ["Workflow"]
    assert denylist.applied_for(ctx.store, ctx.repo.root) == ["Workflow"], (
        "a concurrently applied rule must remain owned so restore can remove it"
    )
    assert denylist.kept_for(ctx.store, ctx.repo.root) == ["CronCreate"]
    assert run(ctx, "toolprune", "restore", "Workflow") == 0
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "Workflow" not in settings.get("permissions", {}).get("deny", [])
    assert denylist.applied_for(ctx.store, ctx.repo.root) == []


# Fix hardening / miha: apply reads proposals and mutates ownership under one lock.
def test_apply_holds_mechanisms_lock_through_proposal_and_ownership(ctx, monkeypatch):
    ctx.store.write("untool.json", {"proposal": ["Workflow"]})
    locked = type(ctx.store).locked
    proposal, apply, set_kept = cli._proposal, denylist.apply, denylist.set_kept
    held = False

    @contextmanager
    def tracked_lock(self, name="state", timeout=10.0):
        nonlocal held
        with locked(self, name, timeout) as acquired:
            if name == "mechanisms":
                held = acquired
            try:
                yield acquired
            finally:
                if name == "mechanisms":
                    held = False

    def require_lock(fn):
        def checked(*args, **kwargs):
            assert held, f"{fn.__name__} must run under the mechanisms lock"
            return fn(*args, **kwargs)
        return checked

    monkeypatch.setattr(type(ctx.store), "locked", tracked_lock)
    monkeypatch.setattr(cli, "_proposal", require_lock(proposal))
    monkeypatch.setattr(denylist, "apply", require_lock(apply))
    monkeypatch.setattr(denylist, "set_kept", require_lock(set_kept))

    assert run(ctx, "toolprune", "apply") == 0
    assert denylist.applied_for(ctx.store, ctx.repo.root) == ["Workflow"]


@pytest.mark.parametrize("action", ["apply", "restore"])
def test_toolprune_does_not_mutate_when_mechanisms_lock_is_busy(ctx, monkeypatch, action):
    denylist.apply(ctx.repo.root, ["Workflow"], ctx.store)
    settings = Path(denylist.settings_path(ctx.repo.root))
    before = settings.read_bytes()
    locked = type(ctx.store).locked

    @contextmanager
    def busy_lock(self, name="state", timeout=10.0):
        if name == "mechanisms":
            yield False
        else:
            with locked(self, name, timeout) as acquired:
                yield acquired

    monkeypatch.setattr(type(ctx.store), "locked", busy_lock)
    tools = ["CronCreate"] if action == "apply" else ["Workflow"]
    assert run(ctx, "toolprune", action, *tools) == 1
    assert settings.read_bytes() == before
    assert denylist.applied_for(ctx.store, ctx.repo.root) == ["Workflow"]
    assert denylist.kept_for(ctx.store, ctx.repo.root) == []


# T3 / kali: every explicit session in a batch must use its own repository pin.
def test_batch_fold_routes_each_session_to_its_pinned_repository(ctx, tmp_path):
    other_work = tmp_path / "other"
    other_work.mkdir()
    other = LiveContext.build(hosts.ClaudeCode(), str(other_work))
    for owner, sid in ((ctx, "sa"), (other, "sb")):
        repos.pin(owner.root, owner.host.name, sid, owner.repo, owner.repo.root)
        owner.store.write(f"sessions/{sid}.json", {
            "session_id": sid, "host": owner.host.name, "cwd": owner.repo.root,
            "started": 1, "ended": 2, "turns": [],
        })
        assert fold.pending_sessions(owner) == [sid]

    assert run(ctx, "fold", "--session", "sa", "--session", "sb") == 0

    for owner, sid in ((ctx, "sa"), (other, "sb")):
        assert set(owner.store.read("folded.json") or {}) == {sid}
        assert owner.store.read(f"sessions/{sid}.json")["folded"] is True
        assert fold.pending_sessions(owner) == []


# T4 / kali: a state file's atomic replacement must not break CLI host selection.
@pytest.mark.parametrize("host_env", [None, "claude"], ids=["default-host", "TE_HOST"])
def test_host_detection_tolerates_a_state_file_renamed_after_listdir(
        ctx, monkeypatch, host_env):
    ctx.store.ensure()
    target = Path(ctx.store.path("untool.json"))
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temporary.write_text("{}", encoding="utf-8")
    listdir = os.listdir
    renamed = False

    def listdir_during_atomic_replace(path):
        nonlocal renamed
        names = listdir(path)
        if os.fspath(path) == ctx.store.base and not renamed:
            # Complete the same atomic rename Store.write performs, after the
            # scanner receives the old listing but before it stats each entry.
            os.replace(temporary, target)
            renamed = True
        return names

    if host_env is not None:
        monkeypatch.setenv("TE_HOST", host_env)
    monkeypatch.setattr(os, "listdir", listdir_during_atomic_replace)

    assert cli.main(["--cwd", ctx.repo.root, "status"]) == 0
    # An explicit environment host may legitimately avoid the scan entirely.
    if renamed:
        assert target.is_file()
        assert json.loads(target.read_text(encoding="utf-8")) == {}


def test_recent_host_skips_an_unreadable_directory(ctx, monkeypatch):
    listdir = os.listdir

    def unreadable(path):
        if os.fspath(path) == ctx.store.base:
            raise PermissionError("state directory temporarily unreadable")
        return listdir(path)

    monkeypatch.setattr(os, "listdir", unreadable)
    assert cli._recent_host(ctx.repo.root) is None
