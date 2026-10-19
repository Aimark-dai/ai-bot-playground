"""Trusted-main Actions entry point. Inert unless explicitly invoked; no retries."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

# -I prevents ambient imports. This directory itself MUST already be trusted.
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('trusted_gate', HERE / 'community_gate.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
ADAPTER = 'tools/community_actions.py'


class Uncertain(RuntimeError):
    pass


class MergeAPI(g.GitHub):
    def publish_ready_once(self, head):
        g.oid(head); g.need(self.token, 'temporary job token missing')
        request = urllib.request.Request(
            'https://api.github.com' + g.ROOT + '/statuses/' + head,
            data=json.dumps({'state': 'success', 'context': 'community-data-policy',
                             'description': 'Trusted merge job validated exact head; not a reusable PR authorization'}).encode(),
            method='POST', headers={'Accept': 'application/vnd.github+json',
                                    'Content-Type': 'application/json',
                                    'Authorization': 'Bearer ' + self.token,
                                    'User-Agent': 'community-native-merge',
                                    'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with self.opener.open(request, timeout=30) as response:
                g.need(response.status == 201, 'status publication not confirmed')
        except Exception:
            raise Uncertain('status publication unconfirmed; no merge attempted; inspect before rerun') from None

    def squash_once(self, number, head):
        g.positive(number); g.oid(head)
        g.need(self.token, 'temporary job token missing')
        request = urllib.request.Request(
            'https://api.github.com' + g.ROOT + '/pulls/' + str(number) + '/merge',
            data=json.dumps({'sha': head, 'merge_method': 'squash'}).encode(), method='PUT',
            headers={'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                     'Authorization': 'Bearer ' + self.token, 'User-Agent': 'community-native-merge',
                     'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(g.MAX_RESPONSE + 1)
                if len(raw) > g.MAX_RESPONSE:
                    raise Uncertain('oversize receipt')
                receipt = g.strict_json(raw)
        except urllib.error.HTTPError as exc:
            # Explicit refusal responses, not a simulated CAS guarantee.
            if exc.code in (403, 404, 405, 409, 422):
                raise g.Rejected('native merge refused: HTTP ' + str(exc.code)) from None
            raise Uncertain('merge response unavailable; inspect PR, never blind retry') from None
        except Exception:
            raise Uncertain('merge response unavailable; inspect PR, never blind retry') from None
        try:
            g.need(receipt['merged'] is True, 'merge not confirmed')
            return g.oid(receipt['sha'])
        except (g.Rejected, KeyError, TypeError):
            raise Uncertain('invalid merge receipt; inspect PR before any further action') from None


def event_request(event, env):
    g.need(env.get('GITHUB_EVENT_NAME') == 'issue_comment', 'wrong event')
    g.need(env.get('GITHUB_REPOSITORY') == g.REPO and env.get('GITHUB_REF') == 'refs/heads/main', 'wrong source')
    g.need(event['action'] == 'created' and event['repository']['id'] == g.REPO_ID, 'event identity')
    g.need(event['repository']['full_name'] == g.REPO, 'event repository')
    number, comment = g.positive(event['issue']['number']), g.positive(event['comment']['id'])
    g.need(event['issue']['pull_request']['url'] == 'https://api.github.com' + g.ROOT + '/pulls/' + str(number), 'not target PR')
    g.need(event['sender']['id'] == event['comment']['user']['id'], 'event sender mismatch')
    return number, comment, g.oid(env.get('GITHUB_SHA'))


def execute(api, event, env, merge=False):
    number, comment, trusted_sha = event_request(event, env)
    # Re-runs after a timeout must be investigated, not used as a retry button.
    g.need(env.get('GITHUB_RUN_ATTEMPT') == '1', 'reruns disabled; reconcile prior outcome')
    pr = api.get('/pulls/' + str(number))
    if pr.get('merged') is True:
        return {'status': 'already-merged-no-write', 'pr': number}
    # Both jobs independently run the whole policy from trusted source.
    plan = g.prepare(api, number, comment, (HERE / 'community_gate.py').read_bytes())
    auth = plan['auth']
    g.need(auth['base'] == trusted_sha, 'main advanced since event; new reviewed request required')
    g.need(event['comment']['body'] == '/merge-community ' + auth['head'], 'event SHA differs from current request')
    g.need(event['comment']['user']['id'] == auth['user']['id'], 'event author mismatch')
    base = g.tree(api, auth['base'])
    g.need(base.get(ADAPTER) == ('100644', 'blob', g.blob_oid(Path(__file__).read_bytes())), 'adapter differs from trusted main')
    branch = api.get('/branches/main')
    g.need(branch['protected'] is True and branch['commit']['sha'] == auth['base'], 'unprotected or changed main')
    # protected=true is only a coarse check. Strict/no-bypass configuration is
    # an external deployment prerequisite, verified by the environment reviewer.
    fresh = g.authorization(api, number, comment)
    g.need(fresh == auth, 'request/head/base changed; no merge')
    if not merge:
        return {'status': 'validated-read-only', 'pr': number, 'head': auth['head'], 'base': auth['base']}
    g.need(env.get('COMMUNITY_MERGE_ENABLED') == 'reviewed', 'deployment not enabled')
    api.publish_ready_once(auth['head'])
    g.need(g.authorization(api, number, comment) == auth, 'state changed after status; no merge')
    commit = api.squash_once(number, auth['head'])
    try:
        final = api.get('/pulls/' + str(number))
        g.need(final['merged'] is True and final['merge_commit_sha'] == commit, 'PR final state mismatch')
    except Exception:
        raise Uncertain('receipt received but PR confirmation failed; inspect PR, do not retry') from None
    return {'status': 'merged', 'pr': number, 'head': auth['head'], 'merge_commit': commit}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--merge', action='store_true')
    args = parser.parse_args()
    try:
        event = g.strict_json(Path(os.environ['GITHUB_EVENT_PATH']).read_bytes())
        result = execute(MergeAPI(os.environ.get('GITHUB_TOKEN')), event, os.environ, args.merge)
        print(json.dumps(result))
    except Uncertain as exc:
        print(json.dumps({'status': 'uncertain', 'reason': str(exc)})); return 3
    except (g.Rejected, KeyError, TypeError, AttributeError, OSError):
        print(json.dumps({'status': 'rejected', 'reason': 'request, policy, source or deployment prerequisite failed'})); return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
