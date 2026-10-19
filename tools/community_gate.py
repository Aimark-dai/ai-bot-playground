"""Read-only evidence for manual, native protected PR merging.

No mutation or status publisher is shipped. Never run from a PR checkout.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

REPO = 'HongChao6/ai-bot-playground'
REPO_ID = 1425566337
ROOT = '/repos/' + REPO
MEMBERS = 'community/members.json'
SCHEMA = 'community/schema/submission.schema.json'
RUNNER = 'tools/community_gate.py'
MAX_RESPONSE = 2 * 1024 * 1024
SHA = re.compile(r'[0-9a-f]{40}')
SCHEMA_RULES = {
    'type': 'object', 'additionalProperties': False,
    'required': ['version', 'bot', 'title', 'body'],
    'properties': {
        'version': {'const': 1, 'type': 'integer'},
        'bot': {'type': 'string', 'minLength': 1, 'maxLength': 80},
        'title': {'type': 'string', 'minLength': 1, 'maxLength': 120},
        'body': {'type': 'string', 'minLength': 1, 'maxLength': 8000},
    },
}


class Rejected(ValueError):
    """Nothing was written by this gate."""


def need(ok, reason):
    if not ok:
        raise Rejected(reason)


def oid(value):
    need(type(value) is str and SHA.fullmatch(value), 'invalid SHA')
    return value


def positive(value):
    need(type(value) is int and value > 0, 'invalid numeric ID')
    return value


def unique_pairs(items):
    out = {}
    for key, value in items:
        need(key not in out, 'duplicate JSON key')
        out[key] = value
    return out


def strict_json(raw):
    def invalid_constant(_):
        raise Rejected('non-finite JSON')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs,
                          parse_constant=invalid_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise Rejected('invalid strict JSON') from exc


def blob_oid(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def payload(raw):
    need(len(raw) <= 16384, 'file too large')
    obj = strict_json(raw)
    need(type(obj) is dict and set(obj) == {'version', 'bot', 'title', 'body'}, 'schema keys')
    need(type(obj['version']) is int and obj['version'] == 1, 'schema version')
    for key, limit in [('bot', 80), ('title', 120), ('body', 8000)]:
        value = obj[key]
        need(type(value) is str and 1 <= len(value) <= limit, 'schema string')
        need(not any(ord(c) < 32 and c not in '\n\r\t' or 0xD800 <= ord(c) <= 0xDFFF for c in value), 'unsafe text encoding')
        # Additional conservative moderation filter, not an execution sandbox.
        need(not re.search(r'[<>]|javascript\s*:|data\s*:|```|#!|\beval\s*\(|\bimport\s|\bfunction\s', value, re.I), 'active-content marker')
    return obj


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Rejected('HTTP redirect refused')


class GitHub:
    """Fixed API host, bounded responses, no redirects or automatic retries."""
    def __init__(self, token=None):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, path):
        need(path.startswith(ROOT + '/') or path == ROOT, 'API target')
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'community-data-gate',
                   'X-GitHub-Api-Version': '2022-11-28'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        request = urllib.request.Request('https://api.github.com' + path, headers=headers, method='GET')
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE + 1)
                need(len(raw) <= MAX_RESPONSE, 'API response limit')
                return strict_json(raw)
        except Exception as exc:
            if isinstance(exc, Rejected):
                raise
            raise Rejected('GitHub read failed; no mutation attempted') from None

    def get(self, suffix):
        return self.request(ROOT + suffix)


def tree(api, commit_sha):
    commit = api.get('/git/commits/' + oid(commit_sha))
    need(commit['sha'] == commit_sha, 'commit mismatch')
    tree_sha = oid(commit['tree']['sha'])
    result = api.get('/git/trees/' + tree_sha + '?recursive=1')
    need(result.get('truncated') is False and result['sha'] == tree_sha, 'incomplete tree')
    need(type(result['tree']) is list and len(result['tree']) <= 5000, 'tree limit')
    entries = {}
    for item in result['tree']:
        p = item['path']
        need(type(p) is str and p and not p.startswith('/') and '\\' not in p and all(x not in ('', '.', '..') for x in p.split('/')), 'noncanonical tree path')
        need(p not in entries, 'duplicate tree path')
        entries[p] = (item['mode'], item['type'], oid(item['sha']))
    return entries


def blob(api, entry, limit):
    need(entry[:2] == ('100644', 'blob'), 'regular nonexecutable blob required')
    result = api.get('/git/blobs/' + entry[2])
    need(result.get('encoding') == 'base64' and type(result.get('size')) is int and 0 <= result['size'] <= limit, 'blob size/encoding')
    try:
        raw = base64.b64decode(''.join(result['content'].split()), validate=True)
    except (ValueError, TypeError):
        raise Rejected('invalid blob encoding') from None
    need(len(raw) == result['size'] and len(raw) <= limit and blob_oid(raw) == entry[2] == result['sha'], 'blob mismatch')
    return raw


def registry(raw, user):
    obj = strict_json(raw)
    need(type(obj) is dict and type(obj.get('version')) is int and obj['version'] == 1 and obj.get('maintained_by') == 'administrators', 'registry format')
    members = obj.get('members')
    need(type(members) is list and len(members) <= 500, 'registry capacity')
    ids, seats, logins = set(), set(), set()
    selected = None
    for m in members:
        uid, seat = positive(m['github_user_id']), positive(m['seat'])
        login = m['github_login']
        need(type(login) is str and login.isascii(), 'registry login')
        login = login.lower()
        need(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?', login), 'registry login')
        need(uid not in ids and seat not in seats and login not in logins and seat <= 500, 'duplicate member/seat/login')
        need(m['slug'] == 'u' + str(uid), 'ID/slug mismatch')
        ids.add(uid); seats.add(seat); logins.add(login)
        if uid == user['id']:
            selected = m
    need(selected is not None and selected['status'] == 'approved', 'not approved')
    need(selected['github_login'].lower() == user['login'].lower(), 'rename requires admin reconciliation')
    return selected['slug']


def authorization(api, pr_number, comment_id):
    positive(pr_number); positive(comment_id)
    repo = api.get('')
    need(repo['id'] == REPO_ID and repo['full_name'] == REPO and repo['default_branch'] == 'main' and not repo['private'] and not repo['archived'], 'repository identity/state')
    pr = api.get('/pulls/' + str(pr_number))
    comment = api.get('/issues/comments/' + str(comment_id))
    need(pr['number'] == pr_number and comment['id'] == comment_id, 'object identity')
    need(comment['issue_url'] == 'https://api.github.com' + ROOT + '/issues/' + str(pr_number), 'comment belongs to another issue')
    need(pr['state'] == 'open' and pr['draft'] is False and not pr.get('merged'), 'PR not open/ready')
    need(pr['base']['repo']['id'] == REPO_ID and pr['base']['ref'] == 'main', 'PR target')
    user = comment['user']
    need(user['type'] == 'User' and pr['user']['type'] == 'User' and positive(user['id']) == positive(pr['user']['id']), 'requester must be real PR author')
    need(user['login'].lower() == pr['user']['login'].lower(), 'identity login mismatch')
    head = oid(pr['head']['sha'])
    need(comment['body'] == '/merge-community ' + head, 'explicit current SHA consent required')
    base = oid(api.get('/git/ref/heads/main')['object']['sha'])
    need(pr['base']['sha'] == base, 'base changed; retry read-only validation')
    return {'base': base, 'head': head, 'user': user, 'comment_updated': comment['updated_at'],
            'pr': pr_number, 'comment': comment_id}


def prepare(api, pr_number, comment_id, runner_bytes):
    auth = authorization(api, pr_number, comment_id)
    base, head = tree(api, auth['base']), tree(api, auth['head'])
    need(base.get(RUNNER) == ('100644', 'blob', blob_oid(runner_bytes)), 'runner is not reviewed main policy')
    for p in (MEMBERS, SCHEMA):
        need(p in base, 'missing trusted policy file')
    slug = registry(blob(api, base[MEMBERS], 262144), auth['user'])
    schema = strict_json(blob(api, base[SCHEMA], 16384))
    need(type(schema) is dict and {k: v for k, v in schema.items() if k not in ('$schema', '$comment', 'title')} == SCHEMA_RULES, 'unsupported schema change; review validator')
    compare = api.get('/compare/' + auth['base'] + '...' + auth['head'])
    need(compare['merge_base_commit']['sha'] == auth['base'] and compare['status'] == 'ahead', 'head must include current base')
    changed = {p for p in set(base) | set(head) if base.get(p) != head.get(p)}
    leaves = [p for p in changed if (head.get(p) or base[p])[1] != 'tree']
    need(1 <= len(leaves) <= 20, 'changed file count')
    allowed_dirs, files, total = set(), [], 0
    for p in sorted(leaves):
        need(re.fullmatch(r'community/submissions/' + re.escape(slug) + r'/[a-z0-9][a-z0-9-]{0,63}\.json', p), 'outside own data directory')
        need(p in head and head[p][:2] == ('100644', 'blob'), 'deletion or unsafe file mode')
        need(p not in base or base[p][:2] == ('100644', 'blob'), 'unsafe prior entry')
        parts = p.split('/')
        for n in range(1, len(parts)):
            parent = '/'.join(parts[:n]); allowed_dirs.add(parent)
            need(head.get(parent, ())[:2] == ('040000', 'tree'), 'unsafe parent')
            need(parent not in base or base[parent][:2] == ('040000', 'tree'), 'unsafe base parent')
        raw = blob(api, head[p], 16384)
        payload(raw)
        total += len(raw)
        need(total <= 131072, 'aggregate size')
        files.append({'path': p, 'blob': head[p][2], 'size': len(raw)})
    need(changed - set(leaves) <= allowed_dirs, 'unexpected directory change')
    return {'auth': auth, 'files': files,
            'policy_blobs': {p: base[p][2] for p in (MEMBERS, SCHEMA, RUNNER)}}


def run(api, pr_number, comment_id, runner_bytes):
    plan = prepare(api, pr_number, comment_id, runner_bytes)
    fresh = authorization(api, pr_number, comment_id)
    need(fresh == plan['auth'], 'head/base/request/identity changed; rerun validation')
    a = plan['auth']
    # This observation is not a GitHub required check and cannot authorize a merge.
    return {'status': 'manual-review-required', 'repository_id': REPO_ID,
            'pr': pr_number, 'comment': comment_id, 'member_id': a['user']['id'],
            'base': a['base'], 'head': a['head'], 'policy_blobs': plan['policy_blobs'],
            'files': plan['files'], 'native_merge_head_sha': a['head']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pr', type=int, required=True)
    parser.add_argument('--comment', type=int, required=True)
    args = parser.parse_args()
    try:
        api = GitHub(os.environ.get('GITHUB_TOKEN'))
        print(json.dumps(run(api, args.pr, args.comment, Path(__file__).read_bytes())))
    except (Rejected, KeyError, TypeError, AttributeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc) if isinstance(exc, Rejected) else 'unexpected API/policy structure'})); return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
