"""Publish the authorized H0 Markdown sources after exact conversion review.

Reuses matching unpublished versions, preserves unrelated documents and stops on
ambiguous matches, edited content, diagnostics or a failed job. No direct DB edits.
"""
import hashlib
import json
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    catalog = json.loads((ROOT / 'evaluation/h0/corpus_catalog.json').read_text(encoding='utf-8'))['documents']
    # Validate all inputs before uploading any source.
    for item in catalog:
        assert hashlib.sha256((ROOT / item['path']).read_bytes()).hexdigest() == item['sha256'], item['id']
    origin = 'http://localhost:3000'
    credentials = json.loads((ROOT / '.artifacts/h1/admin-credentials.json').read_text(encoding='utf-8'))
    output = ROOT / '.artifacts/h3/catalog-publication.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    report = []
    with httpx.Client(base_url=origin + '/api', timeout=60, trust_env=False) as client:
        client.post('/auth/login', json=credentials, headers={'Origin': origin}).raise_for_status()
        headers = {'Origin': origin, 'X-CSRF-Token': client.get('/auth/me').json()['csrf_token']}

        def request(method, path, **kwargs):
            request_headers = headers | ({'Idempotency-Key': str(uuid.uuid4())} if method == 'POST' else {})
            response = client.request(method, path, headers=request_headers, **kwargs)
            response.raise_for_status()
            return response.json()

        def wait(jid):
            until = time.monotonic() + 1200
            while time.monotonic() < until:
                jobs = request('GET', '/admin/jobs')['items']
                job = next((j for j in jobs if j['id'] == jid), None)
                if job and job['status'] in {'completado', 'fallido', 'cancelado'}:
                    if job['status'] != 'completado':
                        raise RuntimeError(f"{jid}: {job['error_code']}")
                    return
                time.sleep(2)
            raise TimeoutError('publication_job_timeout')

        docs, offset = [], 0
        while True:
            page = request('GET', '/admin/documents', params={'offset': offset})
            docs.extend(page['items'])
            if not page['has_more']:
                break
            offset += 50
        for item in catalog:
            matches = [(d, v) for d in docs for v in d['versions'] if v['original_sha256'] == item['sha256']
                       and v['status'] != 'eliminado']
            if len(matches) > 1:
                raise ValueError('ambiguous_catalog_match:' + item['id'])
            if matches:
                doc, version = matches[0]
                if doc['active_version_id'] and doc['active_version_id'] != version['id']:
                    raise ValueError('active_version_conflict:' + item['id'])
            else:
                path = ROOT / item['path']
                data = request('POST', '/admin/documents',
                               files={'file': (path.name, path.read_bytes(), 'text/markdown')},
                               data={'title': path.stem})
                doc = data['document']
                wait(data['job']['id'])
                version = request('GET', '/admin/documents/' + doc['id'])['versions'][0]
                docs.append(doc)
            vid = version['id']
            normalized = request('GET', f'/admin/versions/{vid}/normalized')
            original = client.get(f'/admin/versions/{vid}/original')
            original.raise_for_status()
            expected = (ROOT / item['path']).read_text(encoding='utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
            assert hashlib.sha256(original.content).hexdigest() == item['sha256'], 'original_mismatch'
            assert normalized['markdown'] == expected, 'conversion_or_manual_edit_mismatch'
            assert not normalized['diagnostics'] and normalized['provenance'], 'conversion_review_failed'
            assert normalized['metadata']['visibility'] == 'usuarios', 'scope_review_required'
            lines = len(expected.splitlines())
            assert all(1 <= p['line_start'] <= p['line_end'] <= lines for p in normalized['provenance'])
            if doc['active_version_id'] != vid:
                body = {'expected_revision_id': normalized['revision_id']}
                request('POST', f'/admin/versions/{vid}/review', json=body)
                job = request('POST', f'/admin/versions/{vid}/publish', json=body)
                wait(job['id'])
            active = request('GET', '/admin/documents/' + doc['id'])
            assert active['active_version_id'] == vid
            report.append({'source_id': item['id'], 'document_id': doc['id'], 'version_id': vid,
                           'original_sha256': item['sha256'], 'normalized_sha256': normalized['sha256'],
                           'exact_conversion_review': True, 'visibility': 'usuarios', 'published': True})
            output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
            print('Published ' + item['id'], flush=True)
        client.post('/auth/logout', headers=headers).raise_for_status()


if __name__ == '__main__':
    main()
