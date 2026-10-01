"""Run an agnostic evaluation bank through the real chat and check every answer.

For each turn it checks the expected status (answer, abstain or clarify), that the
sources come from an expected document, that each quote equals its retrieved passage
and is cited, that every figure stated in the answer appears in the cited passages,
that follow-ups keep their subject in the reformulated query and that the downloaded
original matches both the cited and the catalogued SHA-256.

Conversation groups share one chat conversation. Reports containing document passages
stay in the ignored .artifacts folder; the public summary has no passages.
"""
import argparse
import collections
import hashlib
import json
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/api'))
from bibliotecario.chat import numbers  # noqa: E402

EXPECTED = {'answerable': 'answer', 'conversation': 'answer', 'unanswerable': 'abstain', 'ambiguous': 'clarify'}


def plain(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))


def login(client, origin, credentials):
    client.post('/auth/login', json=json.loads(credentials.read_text(encoding='utf-8')),
                headers={'Origin': origin}).raise_for_status()
    identity = client.get('/auth/me').json()
    return identity, {'Origin': origin, 'X-CSRF-Token': identity['csrf_token']}


def published_documents(client):
    rows, offset = [], 0
    while True:
        page = client.get('/admin/documents', params={'offset': offset})
        page.raise_for_status()
        rows.extend(page.json()['items'])
        if not page.json()['has_more']:
            return rows
        offset += 50


def check(case, message, trace, catalog, mapping, client):
    """Return the list of failed checks for one chat turn."""
    failures = []
    expected = EXPECTED[case['kind']]
    sources = message.get('sources') or []
    if expected == 'answer':
        if message.get('status') != 'completed' or not sources:
            failures.append('expected_answer')
        elif not any(source['document_id'] in {mapping[d] for d in case['expected_documents']} for source in sources):
            failures.append('wrong_source')
    else:
        if message.get('status') != 'abstained' or sources:
            failures.append('improper_answer' if message.get('status') == 'completed' else 'unexpected_status')
        elif trace.get('decision', {}).get('action') != expected:
            failures.append('expected_' + expected)
    allowed = {c['chunk_id']: c for c in trace.get('results', [])}
    hashes = {mapping[source['id']]: source['sha256'] for source in catalog if source['id'] in mapping}
    for source in sources:
        if source['chunk_id'] not in allowed or source['quote'] != allowed[source['chunk_id']]['content']:
            failures.append('quote_mismatch')
        if f"[{source['citation_id']}]" not in message['content']:
            failures.append('uncited_source')
        download = client.get(f"/chat/messages/{message['id']}/sources/{source['citation_id']}/original")
        digest = hashlib.sha256(download.content).hexdigest() if download.status_code == 200 else None
        if digest != source['source_sha256'] or (source['document_id'] in hashes and digest != hashes[source['document_id']]):
            failures.append('original_sha256')
    if sources:
        stated = numbers(re.sub(r'\[C\d+\]', '', message['content']))
        # Extractive answers print each passage under its documentary heading, so
        # figures of cited titles and section paths are supported as well.
        documentary = ' '.join([source['quote'] for source in sources] + [source['title'] for source in sources]
                               + [' '.join(source.get('locator', {}).get('section_path', [])) for source in sources])
        if not stated <= numbers(documentary):
            failures.append('unsupported_number')
    if case.get('subject') and plain(case['subject']) not in plain(trace.get('query', '')):
        failures.append('subject_lost')
    return sorted(set(failures))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bank', type=Path, nargs='+', default=[ROOT / 'evaluation/h3/agnostic-validation-v1.jsonl'])
    parser.add_argument('--catalog', type=Path, default=ROOT / 'evaluation/h3/agnostic_corpus_catalog.json')
    parser.add_argument('--scope', choices=['admin', 'usuario'], default='admin')
    parser.add_argument('--credentials', type=Path, default=ROOT / '.artifacts/h1/admin-credentials.json')
    parser.add_argument('--only', nargs='*', default=[], help='Case or conversation IDs to run')
    parser.add_argument('--label', default='', help='Suffix for the report files')
    args = parser.parse_args()
    origin = 'http://localhost:3000'
    catalog = json.loads(args.catalog.read_text(encoding='utf-8'))['documents']
    domains = {source['id']: source['domain'] for source in catalog}
    cases = [json.loads(line) for path in args.bank for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if args.only:
        cases = [c for c in cases if c['id'] in args.only or c.get('conversation_id') in args.only]
    name = args.scope + (('-' + args.label) if args.label else '')
    private = ROOT / f'.artifacts/agnostic-acceptance/{name}.json'
    private.parent.mkdir(parents=True, exist_ok=True)
    rows, conversations = [], {}
    with httpx.Client(base_url=origin + '/api', trust_env=False, timeout=300) as client, \
            httpx.Client(base_url=origin + '/api', trust_env=False, timeout=300) as inspector:
        identity, headers = login(client, origin, args.credentials)
        _, inspector_headers = login(inspector, origin, ROOT / '.artifacts/h1/admin-credentials.json')
        if identity['role'] != args.scope:
            raise ValueError('El ámbito de la prueba debe coincidir con el rol de la cuenta')
        documents = published_documents(inspector)
        mapping = {}
        for source in catalog:
            matches = [d['id'] for d in documents if any(v['id'] == d['active_version_id'] and v['status'] == 'publicado'
                       and v['original_sha256'] == source['sha256'] for v in d['versions'])]
            if len(matches) != 1:
                raise ValueError('Se requiere exactamente una fuente publicada para ' + source['id'])
            mapping[source['id']] = matches[0]
        for case in cases:
            group = case.get('conversation_id')
            if group and group in conversations:
                cid = conversations[group]
            else:
                response = client.post('/chat/conversations', json={'title': 'Aceptación agnóstica: ' + (group or case['id'])},
                                       headers=headers)
                response.raise_for_status()
                cid = response.json()['id']
                if group:
                    conversations[group] = cid
            started = time.monotonic()
            response = client.post(f'/chat/conversations/{cid}/messages', json={'content': case['query']}, headers=headers)
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
            failures = check(case, message, trace, catalog, mapping, client) if message.get('status') != 'error' else ['stream_error']
            domain = ', '.join(sorted({domains[d] for d in case['expected_documents']})) or '—'
            row = {'id': case['id'], 'kind': case['kind'], 'language': case['language'], 'domain': domain,
                   'tags': case.get('tags', []), 'conversation_id': group, 'status': message.get('status'),
                   'chat_outcome': trace.get('chat_outcome'), 'decision': trace.get('decision', {}).get('reason'),
                   'assessment': trace.get('assessment', {}).get('action'),
                   'score': (trace.get('candidates') or [{}])[0].get('rerank_score'),
                   'policy_inherited': trace.get('decision', {}).get('policy_inherited'),
                   'seconds': round(elapsed, 1), 'failures': failures, 'passed': not failures}
            rows.append(row | {'question': case['query'], 'query': trace.get('query'), 'content': message.get('content'),
                               'sources': message.get('sources')})
            private.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f"{'PASS' if row['passed'] else 'FAIL'} {case['id']} [{domain}] {row['status']} "
                  f"{(row['chat_outcome'] or {}).get('reason')} {failures} {elapsed:.0f}s | {case['query']} -> "
                  f"{(message.get('content') or '')[:160]!r}", flush=True)
        client.post('/auth/logout', headers=headers)
        inspector.post('/auth/logout', headers=inspector_headers)
    summary = {'date': datetime.now(ZoneInfo('Europe/Madrid')).date().isoformat(), 'scope': args.scope,
               'banks': {p.resolve().relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.bank},
               'passed': sum(r['passed'] for r in rows), 'total': len(rows),
               'improper_answers': sum('improper_answer' in r['failures'] for r in rows),
               'unsupported_numbers': sum('unsupported_number' in r['failures'] for r in rows),
               'outcomes': dict(collections.Counter(((r['chat_outcome'] or {}).get('reason') or r['status'] or 'none')
                                                    for r in rows if r['status'] == 'completed')),
               'by_kind': {}, 'by_domain': {}, 'failures': {}, 'cases': [{k: v for k, v in r.items()} for r in
                   [{key: row[key] for key in ('id', 'kind', 'language', 'domain', 'status', 'chat_outcome', 'decision',
                     'assessment', 'score', 'policy_inherited', 'seconds', 'failures', 'passed')} for row in rows]]}
    for key, field in (('by_kind', 'kind'), ('by_domain', 'domain')):
        for row in rows:
            entry = summary[key].setdefault(row[field], {'passed': 0, 'total': 0})
            entry['total'] += 1
            entry['passed'] += row['passed']
    summary['failures'] = dict(collections.Counter(f for r in rows for f in r['failures']))
    public = ROOT / f'evaluation/h3/agnostic-acceptance-{name}.json'
    public.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"{summary['passed']}/{summary['total']} correctas, {summary['improper_answers']} indebidas, "
          f"{summary['unsupported_numbers']} cifras sin respaldo; fallos={summary['failures']}")
    sys.exit(0 if summary['passed'] == summary['total'] else 1)


if __name__ == '__main__':
    main()
