"""Offline orchestration/HTTP contract tests; not GitHub protection integration."""
import copy
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
from test_community_gate import Fake, B, H, UID, PATH

FILE = Path(__file__).resolve().parents[1] / 'tools' / 'community_actions.py'
spec = importlib.util.spec_from_file_location('adapter', FILE)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class ActionsFake(Fake):
    def __init__(self):
        super().__init__()
        self.add(self.base, a.ADAPTER, FILE.read_bytes())
        self.head[a.ADAPTER] = self.base[a.ADAPTER]
        self.head['tools'] = self.base['tools']
        self.statuses = []
        self.protected = True
        self.after_write_failure = False
    def get(self, path):
        if path == '/branches/main':
            return {'protected': self.protected, 'commit': {'sha': self.base_sha}}
        if self.writes and self.after_write_failure:
            raise a.g.Rejected('read failed')
        return super().get(path)
    def publish_ready_once(self, head):
        self.statuses.append(head)
    def squash_once(self, number, head):
        # Records call shape only. Does NOT simulate server protection or CAS.
        self.writes.append((number, head))
        self.pr.update(merged=True, merge_commit_sha='e'*40)
        return 'e'*40


class Flow(unittest.TestCase):
    def setUp(self):
        self.api = ActionsFake()
        self.env = dict(GITHUB_EVENT_NAME='issue_comment', GITHUB_REPOSITORY=a.g.REPO,
                        GITHUB_REF='refs/heads/main', GITHUB_SHA=B, GITHUB_RUN_ATTEMPT='1',
                        COMMUNITY_MERGE_ENABLED='reviewed')
        self.event = dict(action='created', repository=dict(id=a.g.REPO_ID, full_name=a.g.REPO),
                          issue=dict(number=2, pull_request=dict(url='https://api.github.com'+a.g.ROOT+'/pulls/2')),
                          comment=copy.deepcopy(self.api.comment), sender=dict(id=UID))
    def run_flow(self, merge=True): return a.execute(self.api, self.event, self.env, merge)
    def reject(self):
        with self.assertRaises(a.g.Rejected): self.run_flow()
        self.assertEqual(self.api.writes, [])
    def test_check_has_no_write(self):
        self.assertEqual(self.run_flow(False)['status'], 'validated-read-only')
        self.assertEqual(self.api.writes, [])
    def test_exact_head_and_confirmed_native_state(self):
        result=self.run_flow()
        self.assertEqual(self.api.writes, [(2,H)])
        self.assertEqual(self.api.statuses, [H])
        self.assertEqual(result['status'],'merged')
    def test_duplicate_after_merge_is_noop(self):
        self.run_flow(); self.assertEqual(self.run_flow()['status'],'already-merged-no-write')
        self.assertEqual(len(self.api.writes),1)
    def test_rerun_forbidden(self): self.env['GITHUB_RUN_ATTEMPT']='2'; self.reject()
    def test_disabled(self): self.env['COMMUNITY_MERGE_ENABLED']=''; self.reject()
    def test_other_event(self): self.env['GITHUB_EVENT_NAME']='pull_request_target'; self.reject()
    def test_other_repo(self): self.event['repository']['id']=1; self.reject()
    def test_other_ref(self): self.env['GITHUB_REF']='refs/pull/2/merge'; self.reject()
    def test_old_workflow_revision(self): self.env['GITHUB_SHA']='f'*40; self.reject()
    def test_event_author_forged(self): self.event['comment']['user']['id']=7; self.reject()
    def test_request_edited_after_event(self): self.event['comment']['body']='/merge-community '+'f'*40; self.reject()
    def test_unprotected_main(self): self.api.protected=False; self.reject()
    def test_unreviewed_adapter(self): self.api.base[a.ADAPTER]=('100644','blob','f'*40); self.reject()
    def test_revalidates_member(self):
        self.api.member['status']='revoked'; self.api.policy(self.api.members); self.reject()
    def test_revalidates_foreign_path(self):
        self.api.add(self.api.head,'.github/workflows/attack.yml',b'bad'); self.reject()
    def test_head_change_before_write(self):
        self.api.before_second_auth=lambda x:x.pr['head'].update(sha='f'*40); self.reject()
    def test_base_change_before_write(self):
        self.api.before_second_auth=lambda x:setattr(x,'base_sha','f'*40); self.reject()
    def test_uncertain_write_is_not_retried(self):
        with patch.object(self.api,'squash_once',side_effect=a.Uncertain('timeout')) as method:
            with self.assertRaises(a.Uncertain): self.run_flow()
            self.assertEqual(method.call_count,1)
    def test_status_failure_prevents_merge(self):
        with patch.object(self.api,'publish_ready_once',side_effect=a.Uncertain('timeout')) as method:
            with self.assertRaises(a.Uncertain): self.run_flow()
            self.assertEqual(method.call_count,1)
            self.assertEqual(self.api.writes,[])
    def test_head_change_after_status_prevents_merge(self):
        def publish(_): self.api.pr['head']['sha']='f'*40
        with patch.object(self.api,'publish_ready_once',side_effect=publish): self.reject()

    def test_confirmation_failure_is_uncertain(self):
        self.api.after_write_failure=True
        with self.assertRaises(a.Uncertain): self.run_flow()
        self.assertEqual(len(self.api.writes),1)


class HTTPContract(unittest.TestCase):
    def setUp(self): self.api=a.MergeAPI('fake-test-value')
    def response(self, raw):
        response=MagicMock(); response.__enter__.return_value.read.return_value=raw
        return response
    def test_only_native_squash_request(self):
        with patch.object(self.api.opener,'open',return_value=self.response(b'{"merged":true,"sha":"'+b'e'*40+b'"}')) as method:
            self.assertEqual(self.api.squash_once(2,H),'e'*40)
            req=method.call_args.args[0]
            self.assertEqual(req.full_url,'https://api.github.com'+a.g.ROOT+'/pulls/2/merge')
            self.assertEqual(req.get_method(),'PUT')
            self.assertEqual(a.json.loads(req.data),{'sha':H,'merge_method':'squash'})
            self.assertEqual(method.call_count,1)
    def test_status_publication_is_exact_head(self):
        response=self.response(b'{}'); response.__enter__.return_value.status=201
        with patch.object(self.api.opener,'open',return_value=response) as method:
            self.api.publish_ready_once(H)
            req=method.call_args.args[0]
            self.assertEqual(req.full_url,'https://api.github.com'+a.g.ROOT+'/statuses/'+H)
            self.assertEqual(req.get_method(),'POST')
            self.assertEqual(a.json.loads(req.data)['context'],'community-data-policy')
            self.assertEqual(method.call_count,1)
    def test_status_timeout_never_retries(self):
        with patch.object(self.api.opener,'open',side_effect=TimeoutError()) as method:
            with self.assertRaises(a.Uncertain): self.api.publish_ready_once(H)
            self.assertEqual(method.call_count,1)

    def test_refusal_codes(self):
        for code in (403,404,405,409,422):
            with self.subTest(code=code), patch.object(self.api.opener,'open',side_effect=urllib.error.HTTPError('fixed',code,'refused',{},io.BytesIO())) as method:
                with self.assertRaises(a.g.Rejected): self.api.squash_once(2,H)
                self.assertEqual(method.call_count,1)
    def test_ambiguous_codes_and_transport(self):
        for exc in (TimeoutError(),urllib.error.HTTPError('fixed',500,'failure',{},io.BytesIO())):
            with patch.object(self.api.opener,'open',side_effect=exc) as method:
                with self.assertRaises(a.Uncertain): self.api.squash_once(2,H)
                self.assertEqual(method.call_count,1)
    def test_malformed_or_unconfirmed_receipt(self):
        for raw in (b'[]',b'null',b'{}',b'{"merged":false}',b'not json'):
            with self.subTest(raw=raw), patch.object(self.api.opener,'open',return_value=self.response(raw)):
                with self.assertRaises(a.Uncertain): self.api.squash_once(2,H)
    def test_token_required(self):
        with self.assertRaises(a.g.Rejected): a.MergeAPI().squash_once(2,H)


if __name__ == '__main__': unittest.main(verbosity=2)
