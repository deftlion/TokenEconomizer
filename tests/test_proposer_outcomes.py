"""Record proposer outcomes without retaining any model or session text."""
import json
from types import SimpleNamespace

import pytest

from fixtures import write_claude_transcript
from tokeneconomizer.microskills import Distiller
from tokeneconomizer.plugin import cli, fold, sidecall
from tokeneconomizer.plugin.config import LiveConfig
from tokeneconomizer.plugin.store import Store


@pytest.mark.parametrize(('reply', 'status'), [
    (None, 'no-reply'), ('  ', 'no-reply'), ('{SECRET', 'malformed-json'),
    ('["SECRET"]', 'non-object-json'), ('null', 'non-object-json'),
    ('```json\n{"facts": [], "extractors": []}\n```', 'empty'),
    ('{"facts": "SECRET"}', 'filtered'), ('{"facts": [null]}', 'filtered'),
])
def test_proposal_reply_status(reply, status):
    d = Distiller('acme/widget', runner=lambda *_: (reply, 2))
    d.window = [{}]
    d._maybe_propose()
    assert d.last_proposal['status'] == status
    assert 'SECRET' not in json.dumps(d.last_proposal)
    assert d.last_propose == d.now
    assert d.opt_tokens == 2


def test_runner_failure_is_counted_without_exception_details():
    def runner(*_):
        raise RuntimeError('SECRET')

    d = Distiller('acme/widget', runner=runner)
    d.window = [{}]
    d._maybe_propose()
    assert d.last_proposal == {'status': 'runner-error'}
    assert d.last_propose == d.now
    assert not d.opt_tokens


def test_live_fold_preserves_latest_tick_and_reports_only_counts(tmp_path, monkeypatch, capsys):
    import tokeneconomizer.microskills.distiller as dist

    monkeypatch.setattr(dist, 'PROPOSE_EVERY', 3)
    ctx = SimpleNamespace(config=LiveConfig(microskills='envfacts+distiller',
                                            microskills_propose_every=3),
                          host=SimpleNamespace(name='pi'), root=str(tmp_path),
                          store=Store(tmp_path), mech_dir=tmp_path / 'mechanisms',
                          repo=SimpleNamespace(label='acme/widget'))
    accepted = {'id': 'SECRET-valid', 'claim': 'SECRET claim', 'injection': 'SECRET advice',
                'detector': {'scope': 'ran_tests', 'confirm': 'passed', 'fired': 'ran_tests'},
                'cite': ['w-0', 'w-1']}
    payload = json.dumps({'extractors': [None, {'name': 'SECRET-invalid', 'pattern': '['},
                                         {'name': 'SECRET-extractor', 'pattern': 'pytest'}],
                          'facts': [None, accepted, {**accepted, 'id': 'SECRET-rejected',
                                                     'cite': ['w-0']}]})
    monkeypatch.setattr(sidecall, 'runner_for', lambda *_, **__: lambda *_: (payload, 2.0))
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    write_claude_transcript(str(run_dir / 'transcript.jsonl'),
                            [('bash', {'command': 'pytest'}, '1 passed')])
    fold._fold_microskills(ctx, None, run_dir, 'w-0')
    assert 'last_proposal' not in ctx.store.read('injection.json')
    result = fold._fold_microskills(ctx, None, run_dir, 'w-1')
    assert result['optimizer_tokens'] == 2.0
    inj = ctx.store.read('injection.json')
    outcome = inj['last_proposal']
    assert outcome['status'] == 'processed'
    assert outcome['extractors_filtered'] == outcome['facts_filtered'] == 1
    assert outcome['extractors_admitted'] == outcome['extractors_rejected'] == 1
    assert outcome['fact_outcomes'] == {'admitted': 1, 'grounding-fail': 1}
    assert 'SECRET' not in json.dumps(outcome)
    assert not inj['facts']['SECRET-valid']['inject']
    assert fold._fold_microskills(ctx, None, run_dir, 'w-2', imported=True)['optimizer_tokens'] == 0
    assert ctx.store.read('injection.json')['last_proposal'] == outcome
    monkeypatch.setattr(cli, '_ctx', lambda _: ctx)
    assert cli.cmd_microskills(SimpleNamespace(action='show', ids=[])) == 0
    assert 'grounding-fail' in capsys.readouterr().out

    # Subsequent sessions build evidence through normal, separately loaded folds.
    for i in range(3, 6):
        fold._fold_microskills(ctx, None, run_dir, f'w-{i}', imported=True)
    inj = ctx.store.read('injection.json')
    assert inj['facts']['SECRET-valid']['inject']
    assert 'SECRET advice' in inj['rendered']
    assert inj['last_proposal'] == outcome
