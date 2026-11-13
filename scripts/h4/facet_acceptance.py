"""Acceptance of the answer-per-facet contract with a two-part question bank.

For every case of `facet-validation-v1.jsonl` it opens a fresh conversation,
sends the two-part question in `explain` mode and checks the frozen contract:

- ``result.parts`` holds exactly one part per bank part (length 2).
- Every part with expected documents is ``completed`` and cites at least one
  expected document and no document outside its list. Citations are attributed
  to a part through that part's own retrieval pool: a global source belongs to
  part ``i`` when its ``chunk_id`` was retrieved by ``result.parts[i].results``
  (the composition answers each part from its own evidence; nothing is judged
  from the prose).
- Every part with ``expected_documents: []`` abstains.
- The global status is ``completed`` for ``both``/``partial`` and ``abstained``
  for ``none``.
- The literal closing sentence appears exactly once whenever there is a
  composition and never when the turn abstains.
- Every ``[Cn]`` marker in the content exists in ``sources`` and every source
  is cited back (no orphan markers, in either direction).

Reports containing document passages stay in the ignored ``.artifacts`` folder;
the public summary has no passages. Login and percentile helpers are imported
from ``agnostic_acceptance.py`` without modifying it.
"""
import argparse
import collections
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/api'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agnostic_acceptance import login, percentile, published_documents  # noqa: E402

# Frozen closing sentence of the composition (h8-answer-per-facet contract).
CLOSING = 'Esta composición no afirma ninguna relación entre las dos partes: resume la evidencia de cada una por separado.'
GLOBAL_STATUS = {'both': 'completed', 'partial': 'completed', 'none': 'abstained'}


def closing_counts(content):
    """How many times the frozen closing sentence appears in the content."""
    return (content or '').count(CLOSING)


def content_markers(content):
    """The set of ``[Cn]`` markers present in the composition text."""
    return set(re.findall(r'\[C\d+\]', content or ''))


def source_markers(sources):
    """The set of ``[Cn]`` markers the message sources define."""
    return {f"[{source['citation_id']}]" for source in sources or []}


def part_pool_chunk_ids(trace, index):
    """Chunk ids the retrieval pool of part ``index`` holds (or None if unknown).

    A present-but-empty pool is known-empty (empty set); only an absent
    ``results`` key makes the attribution unknown.
    """
    parts = trace.get('parts') or []
    if index >= len(parts):
        return None
    results = parts[index].get('results')
    if results is not None:
        return {result['chunk_id'] for result in results}
    return None


def part_cited_documents(trace, sources, index):
    """Documents a part cites: global sources whose chunk that part retrieved.

    Judged from the trace, never from the prose. Primary attribution is the
    part's own retrieval pool (``parts[i].results`` chunk membership); a
    secondary path accepts explicit ``document_ids`` on the outcome part when
    the trace carries them instead of the pool.
    """
    sources = sources or []
    chunk_pool = part_pool_chunk_ids(trace, index)
    if chunk_pool:
        return {source['document_id'] for source in sources if source['chunk_id'] in chunk_pool}
    outcome_part = ((trace.get('chat_outcome') or {}).get('parts') or [])
    if index < len(outcome_part) and outcome_part[index].get('document_ids'):
        allowed = set(outcome_part[index]['document_ids'])
        return {source['document_id'] for source in sources if source['document_id'] in allowed}
    return None


def check_part(case_part, outcome, cited_documents, mapping):
    """Failures of one facet: expected documents, status and honest abstention."""
    expected = {mapping[d] for d in case_part.get('expected_documents') or []}
    failures = []
    status = (outcome or {}).get('status')
    if expected:
        if status != 'completed':
            failures.append('part_not_completed')
        if cited_documents is None:
            failures.append('part_unattributable')
        else:
            if not cited_documents & expected:
                failures.append('part_missing_document')
            if cited_documents - expected:
                failures.append('part_outside_document')
    elif status == 'completed' or cited_documents:
        failures.append('improper_answer')
    elif status != 'abstained':
        failures.append('unexpected_status')
    return failures


def check_case(case, message, trace, mapping):
    """Every contract check for one two-part turn, judged without the prose."""
    failures = []
    sources = message.get('sources') or []
    content = message.get('content') or ''
    outcome = trace.get('chat_outcome') or {}
    outcome_parts = outcome.get('parts') or []
    parts = trace.get('parts') or []
    if len(parts) != len(case['parts']):
        failures.append('parts_length')
    else:
        for index, case_part in enumerate(case['parts']):
            failures += check_part(case_part, outcome_parts[index] if index < len(outcome_parts) else {},
                                   part_cited_documents(trace, sources, index), mapping)
    expected_global = GLOBAL_STATUS[case['kind']]
    if outcome.get('status') != expected_global:
        failures.append('global_status')
    closing = closing_counts(content)
    if expected_global == 'completed':
        if closing != 1:
            failures.append('closing_repeated' if closing > 1 else 'closing_missing')
    elif closing:
        failures.append('closing_present')
    if content_markers(content) - source_markers(sources):
        failures.append('orphan_marker')
    if source_markers(sources) - content_markers(content):
        failures.append('uncited_source')
    return sorted(set(failures))


def catalog_mapping(inspector, catalog, credentials, origin):
    """Catalog source id -> published document id, matched by original SHA-256.

    Also returns the inspector's authenticated headers so the caller can log
    the inspector out (the login here would otherwise leak a session).
    """
    _, inspector_headers = login(inspector, origin, credentials)
    documents = published_documents(inspector)
    mapping = {}
    for source in catalog:
        matches = [d['id'] for d in documents if any(v['id'] == d['active_version_id'] and v['status'] == 'publicado'
                   and v['original_sha256'] == source['sha256'] for v in d['versions'])]
        if len(matches) != 1:
            raise ValueError('Se requiere exactamente una fuente publicada para ' + source['id'])
        mapping[source['id']] = matches[0]
    return mapping, inspector_headers


def part_states(outcome_parts):
    """The observable state of each facet outcome, without document text."""
    return [{'status': part.get('status'), 'reason': part.get('reason'),
             'citations': part.get('citations'), 'documents': part.get('documents')}
            for part in outcome_parts or []]


def build_summary(rows, banks, scope, date=None):
    """The public summary from the run rows; pure, so the rules test it offline.

    Percentiles measure ``chat_latency.total_ms`` of the rows that carry a
    trace; rows without one (a failed trace load) still count for the pass
    totals and the failure counters, but not for the latency percentiles.
    """
    latencies = [row['chat_latency']['total_ms'] for row in rows if row.get('chat_latency')]
    summary = {'date': date or datetime.now(ZoneInfo('Europe/Madrid')).date().isoformat(), 'scope': scope,
               'banks': banks,
               'passed': sum(row['passed'] for row in rows), 'total': len(rows),
               'improper': sum('improper_answer' in row['failures'] or 'part_outside_document' in row['failures']
                               for row in rows),
               'latency': {'n': len(latencies), 'p50': percentile(latencies, .5), 'p95': percentile(latencies, .95)},
               'by_kind': {}, 'failures': dict(collections.Counter(f for row in rows for f in row['failures'])),
               'cases': [{key: row[key] for key in ('id', 'kind', 'language', 'domain', 'tags', 'status', 'parts',
                                                    'chat_outcome', 'chat_latency', 'seconds', 'failures', 'passed')}
                         for row in rows]}
    for row in rows:
        entry = summary['by_kind'].setdefault(row['kind'], {'passed': 0, 'total': 0})
        entry['total'] += 1
        entry['passed'] += row['passed']
    return summary


def close_sessions(logouts):
    """Log every session out; a failing close is a warning, never a lost run."""
    for label, client, auth_headers in logouts:
        try:
            client.post('/auth/logout', headers=auth_headers)
        except httpx.HTTPError as exc:
            print(f'aviso: el logout de {label} falló: {exc}', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bank', type=Path, nargs='+',
                        default=[ROOT / 'evaluation/h3/facet-validation-v1.jsonl'])
    parser.add_argument('--catalog', type=Path, default=ROOT / 'evaluation/h3/agnostic_corpus_catalog.json')
    parser.add_argument('--scope', choices=['admin', 'usuario'], default='admin')
    parser.add_argument('--label', default='', help='Suffix appended to the private report name')
    parser.add_argument('--credentials', type=Path, default=ROOT / '.artifacts/h1/admin-credentials.json')
    parser.add_argument('--origin', default='http://localhost:3000')
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding='utf-8'))['documents']
    domains = {source['id']: source['domain'] for source in catalog}
    cases = [json.loads(line) for path in args.bank for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    name = args.scope + args.label
    private = ROOT / f'.artifacts/facet-acceptance/{name}.json'
    private.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    admin_credentials = ROOT / '.artifacts/h1/admin-credentials.json'
    with httpx.Client(base_url=args.origin + '/api', trust_env=False, timeout=300) as client, \
            httpx.Client(base_url=args.origin + '/api', trust_env=False, timeout=300) as inspector:
        identity, headers = login(client, args.origin, args.credentials)
        if identity['role'] != args.scope:
            raise ValueError('El ámbito de la prueba debe coincidir con el rol de la cuenta')
        mapping, inspector_headers = catalog_mapping(inspector, catalog, admin_credentials, args.origin)
        for case in cases:
            response = client.post('/chat/conversations', json={'title': 'Aceptación por facetas: ' + case['id']},
                                   headers=headers)
            response.raise_for_status()
            cid = response.json()['id']
            started = time.monotonic()
            response = client.post(f'/chat/conversations/{cid}/messages',
                                   json={'content': case['query'], 'mode': 'explain'}, headers=headers)
            response.raise_for_status()
            elapsed = time.monotonic() - started
            message = [json.loads(line) for line in response.text.splitlines()][-1].get('message', {})
            if not isinstance(message, dict):
                message = {'status': 'error', 'error': message, 'sources': []}
            trace = {}
            if message.get('retrieval_run_id'):
                detail = inspector.get('/admin/retrieval/runs/' + message['retrieval_run_id'])
                detail.raise_for_status()
                trace = detail.json()['result']
            failures = check_case(case, message, trace, mapping) if message.get('status') != 'error' else ['stream_error']
            documents = {d for part in case['parts'] for d in part['expected_documents']}
            domain = ', '.join(sorted({domains[d] for d in documents})) or '—'
            outcome = trace.get('chat_outcome') or {}
            row = {'id': case['id'], 'kind': case['kind'], 'language': case['language'], 'domain': domain,
                   'tags': case.get('tags', []), 'status': message.get('status'),
                   'parts': part_states(outcome.get('parts')), 'chat_outcome': outcome,
                   'chat_latency': trace.get('chat_latency'), 'seconds': round(elapsed, 1),
                   'failures': failures, 'passed': not failures}
            rows.append(row | {'question': case['query'], 'query': case['query'], 'content': message.get('content'),
                               'sources': message.get('sources'),
                               'parts_debug': [{'pool_documents': sorted({r['document_id'] for r in part.get('results') or []}),
                                                'cited_documents': sorted(part_cited_documents(trace, message.get('sources') or [], index) or [])}
                                               for index, part in enumerate(trace.get('parts') or [])]})
            private.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f"{'PASS' if row['passed'] else 'FAIL'} {case['id']} [{domain}] {row['status']} "
                  f"{[part['status'] for part in row['parts']]} {failures} {elapsed:.0f}s | {case['query']} -> "
                  f"{(message.get('content') or '')[:160]!r}", flush=True)
        # The summary and both reports are written BEFORE the logout, inside a
        # try/finally: a failing close (network, session already dead) must not
        # lose the run's evidence or its exit code.
        exit_code = 1
        try:
            summary = build_summary(rows, [str(p) for p in args.bank], args.scope)
            public = ROOT / f'evaluation/h3/facet-acceptance-{args.scope}.json'
            public.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f"{summary['passed']}/{summary['total']} correctas, {summary['improper']} impropias "
                  f"(respondida sin abstenerse o cita fuera de sus documentos); fallos={summary['failures']}")
            print('latencia chat (ms):', json.dumps(summary['latency'], ensure_ascii=False))
            exit_code = 0 if summary['passed'] == summary['total'] else 1
        finally:
            close_sessions([('client', client, headers), ('inspector', inspector, inspector_headers)])
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
