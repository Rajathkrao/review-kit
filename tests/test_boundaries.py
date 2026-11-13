"""Output boundaries (validation, posting, Codex, evals, auto-merge) without model or GitHub access."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import unittest
from unittest import mock

from test_reliability import TemporaryCase, SCRIPTS, ROOT, review, finding
import collect
import post_review
import review_data
import render_html


class BoundaryTests(TemporaryCase):
    def test_nonempty_scope_cannot_transition_to_nothing_to_review(self):
        with self.assertRaises(ValueError):
            review_data.validate_review(review(status='nothing-to-review'),
                                        {'size': 'small', 'collection_status': 'completed'})

    def test_unknown_collection_state_cannot_produce_completed_review(self):
        with self.assertRaises(ValueError):
            review_data.validate_review(review(), {'collection_status': 'collecting'})

    def test_diff_content_looking_like_file_headers_is_commentable(self):
        diff = ('diff --git a/a.js b/a.js\n--- a/a.js\n+++ b/a.js\n'
                '@@ -1,2 +1,3 @@\n let x = 0;\n+++ x;\n report(x);\n')
        self.assertEqual(set(post_review.commentable_lines(diff)['a.js']), {1, 2, 3})

    def test_submit_requires_unchanged_preview(self):
        self.package()
        post_review.build(self.pkg)
        (self.pkg / 'findings.json').write_text(json.dumps(review([finding()])))
        with mock.patch.object(sys, 'argv', ['post_review.py', str(self.pkg), '--submit']), \
             mock.patch.object(post_review, 'check_eligible'), \
             mock.patch.object(post_review, 'gh_api') as api:
            with self.assertRaises(ValueError):
                post_review.main()
            api.assert_not_called()

    def test_submit_without_preview_never_calls_github(self):
        self.package()
        with mock.patch.object(sys, 'argv', ['post_review.py', str(self.pkg), '--submit']), \
             mock.patch.object(post_review, 'check_eligible'), \
             mock.patch.object(post_review, 'gh_api') as api:
            with self.assertRaises(ValueError):
                post_review.main()
            api.assert_not_called()

    def test_codex_retry_cannot_reuse_output_from_failed_attempt(self):
        self.package()
        self.cli('codex', '''import sys,json
from pathlib import Path
if sys.argv[1] in ['--version','login']: sys.exit(0)
if '--output-schema' in sys.argv:
 Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(dict(
   verdict='approve',summary='Stale attempt',findings=[],next_steps=[])))
 print("unexpected argument '--output-schema'",file=sys.stderr)
 sys.exit(1)
# Retry exits successfully but produces no result.
''')
        result = subprocess.run(['bash', str(SCRIPTS / 'codex_review.sh'), str(self.pkg)],
                                env=self.env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.pkg / 'candidates/second-model.json').exists())


class BaselineTests(TemporaryCase):
    def test_adversarial_baseline_rejects_setup_model_and_schema_failures(self):
        here = self.root / 'evals'
        here.mkdir()
        shutil.copy(ROOT / 'evals/run_adversarial_baseline.sh', here)
        shutil.copytree(ROOT / 'skills', self.root / 'skills')
        (here / 'fixtures').mkdir()
        shutil.copytree(self.repo, here / 'fixtures/demo')
        self.cli('claude', '''import os,sys
print(os.environ.get('MODEL_RESULT','{}'))
sys.exit(int(os.environ.get('MODEL_EXIT','0')))
''')
        good = dict(verdict='approve', summary='No issue', findings=[], next_steps=[])
        success = dict(is_error=False, subtype='success', result=json.dumps(good))
        cases = [('setup', 'missing', success, 0), ('process', 'main', success, 1),
                 ('empty', 'main', {}, 0),
                 ('error', 'main', {**success, 'is_error': True}, 0),
                 ('malformed', 'main', {**success, 'result': 'No bugs'}, 0),
                 ('schema', 'main', {**success, 'result': '{}'}, 0),
                 ('valid', 'main', success, 0)]
        for name, branch, output, exit_code in cases:
            with self.subTest(name=name):
                env = {**self.env, 'MODEL_RESULT': json.dumps(output), 'MODEL_EXIT': str(exit_code)}
                result = subprocess.run(['bash', str(here / 'run_adversarial_baseline.sh'),
                                         'demo', branch, name], env=env, capture_output=True)
                self.assertEqual(result.returncode == 0, name == 'valid', result.stderr)
                status = json.loads((here / 'runs' / name / 'status.json').read_text())
                self.assertEqual(status['execution_status'], 'completed' if name == 'valid' else 'failed')
                self.assertEqual((here / 'runs' / name / 'report.md').exists(), name == 'valid')
        saved = (here / 'runs/valid/status.json').read_bytes()
        retry = subprocess.run(['bash', str(here / 'run_adversarial_baseline.sh'),
                                'demo', 'main', 'valid'], env=self.env, capture_output=True)
        self.assertNotEqual(retry.returncode, 0)
        self.assertEqual((here / 'runs/valid/status.json').read_bytes(), saved)


class AutoMergeTests(TemporaryCase):
    def test_auto_merge_requires_verified_protection_and_pins_the_head(self):
        workflow = (ROOT / '.github/workflows/auto-merge.yml').read_text()
        script = textwrap.dedent(workflow.split('        run: |\n', 1)[1])
        sentinel = self.root / 'merged.json'
        self.cli('gh', '''import json,os,sys
from pathlib import Path
if sys.argv[1]=='api':
 print(os.environ.get('PROTECTION','{}'))
 sys.exit(int(os.environ.get('LOOKUP_EXIT','0')))
Path(os.environ['MERGE_ARGS']).write_text(json.dumps(sys.argv[1:]))
''')
        checks = dict(contexts=['validate'])
        approval = dict(required_approving_review_count=1)
        for label, protection, code, allowed in [
                ('unprotected', {}, 0, False),
                ('review-only', {'required_pull_request_reviews': approval}, 0, False),
                ('ci-only', {'required_status_checks': checks}, 0, False),
                ('lookup-failed', {}, 1, False),
                ('malformed', None, 0, False),
                ('gated', {'required_status_checks': checks,
                           'required_pull_request_reviews': approval}, 0, True)]:
            with self.subTest(label=label):
                sentinel.unlink(missing_ok=True)
                env = {**self.env, 'PR': '1', 'REPO': 'owner/repo', 'BASE': 'main',
                       'HEAD': self.base, 'MERGE_ARGS': str(sentinel),
                       'PROTECTION': json.dumps(protection), 'LOOKUP_EXIT': str(code)}
                result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script],
                                        env=env, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(sentinel.exists(), allowed)
                if allowed:
                    args = json.loads(sentinel.read_text())
                    self.assertEqual(args[-2:], ['--match-head-commit', self.base])


if __name__ == '__main__':
    unittest.main()
