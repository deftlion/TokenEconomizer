"""Only a Pi shutdown with positive evidence of no conversation is an empty session."""
import errno
import json
from types import SimpleNamespace

import pytest

from tokeneconomizer.plugin import fold
from tokeneconomizer.plugin.config import LiveConfig
from tokeneconomizer.plugin.controller import LiveController
from tokeneconomizer.plugin.hosts import Pi
from tokeneconomizer.plugin.store import Store
from tokeneconomizer.trace import jsonl


@pytest.mark.parametrize('marked,source,expect', [
    (True, 'missing', 'empty'),
    (False, 'missing', 'error'),    # even if no turns were recorded
    (True, 'late', 'learn'),        # never discard a file available by the time we fold
    (True, 'denied', 'error'),      # a present but unreadable file is not missing
    (False, 'denied', 'error'),
])
def test_pi_empty_marker_survives_detached_handoff(tmp_path, monkeypatch, marked, source, expect):
    ctx = SimpleNamespace(config=LiveConfig(), host=Pi(), root=str(tmp_path), env={},
                          store=Store(tmp_path), repo=SimpleNamespace(label='acme/widget',
                          root=str(tmp_path)))
    path = tmp_path / 'pi.jsonl'
    payload = {'session_id': 'session', 'transcript_path': str(path), 'cwd': str(tmp_path)}
    ctx.store.write('sessions/session.json', {'started': 1, 'turns': []})
    if marked:
        payload['pi_empty_session'] = True
    scheduled = []
    monkeypatch.setattr(fold, 'spawn_fold', lambda ctx, ids: scheduled.extend(ids))
    LiveController(ctx, payload).session_end()
    assert scheduled == ['session']

    if source != 'missing':
        events = [{'type': 'session', 'cwd': str(tmp_path)},
                  {'type': 'message', 'id': 'u', 'parentId': None,
                   'message': {'role': 'user', 'content': 'synthetic prompt'}}]
        path.write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
    if source == 'denied':
        def deny(*_, **__):
            raise PermissionError(errno.EACCES, 'injected read failure')
        monkeypatch.setattr(jsonl, 'open', deny, raising=False)
    calls = []
    monkeypatch.setattr(fold, '_fold_microskills', lambda *_, **__: calls.append('microskills'))
    monkeypatch.setattr(fold, '_fold_toolprune', lambda *_, **__: calls.append('toolprune'))

    row = fold.fold_session(ctx, 'session')
    assert row['turns'] == 0
    assert row.get('error') == ('transcript unreadable' if expect == 'error' else None)
    assert row.get('empty_session', False) is (expect == 'empty')
    assert calls == (['microskills', 'toolprune'] if expect == 'learn' else [])
    assert fold.fold_session(ctx, 'session') is None
    assert list(ctx.store.read_lines('ledger.jsonl')) == [row]
