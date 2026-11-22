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


class CommentFormatTests(TemporaryCase):
    DIFF = ('diff --git a/code.py b/code.py\n--- a/code.py\n+++ b/code.py\n'
            '@@ -1,1 +1,4 @@\n value = 1\n+a = 1\n+b = 2\n+c = 3\n')

    def build(self, findings, verdict):
        self.package(dict(review(findings), verdict=verdict))
        (self.pkg / 'diff.patch').write_text(self.DIFF)
        payload, _ = post_review.build(self.pkg)
        return payload

    def test_summary_ranks_by_severity_and_folds_minors(self):
        minor = dict(finding(), id='F1', title='Nit name', severity='minor', line_start=2, line_end=2)
        crit = dict(finding(), id='F2', title='Data loss', severity='critical', line_start=3, line_end=3)
        p = self.build([minor, crit], 'dont-ship')
        body = p['body']
        self.assertTrue(body.startswith("<!-- review-kit:summary -->\n## 🔴 Don't merge yet"))
        self.assertIn('🔴 1 critical · 🟡 1 minor', body)
        self.assertIn('<summary>🟡 Minor (1)</summary>', body)
        self.assertLess(body.index('Data loss'), body.index('Nit name'))
        # Minor findings stay out of the inline comments.
        self.assertEqual([c['line'] for c in p['comments']], [3])
        self.assertIn('🔴 **Critical** · Data loss', p['comments'][0]['body'])
        self.assertIn('<summary>🤖 Prompt for AI agents</summary>', p['comments'][0]['body'])

    def test_suggestion_block_only_when_comment_covers_whole_range(self):
        exact = dict(finding(), line_start=2, line_end=4, suggestion='a = b = c = 1')
        c = self.build([exact], 'ship-after-fixes')['comments'][0]
        self.assertEqual((c['start_line'], c['line']), (2, 4))
        self.assertIn('```suggestion\na = b = c = 1\n```', c['body'])
        # Lines 4-6 only partly in the diff: GitHub would replace the wrong lines.
        partial = dict(finding(), line_start=4, line_end=6, suggestion='x = 1')
        c = self.build([partial], 'ship-after-fixes')['comments'][0]
        self.assertNotIn('```suggestion', c['body'])
        self.assertIn('Replacement for lines 4-6', c['body'])

    def test_fence_survives_backticks_and_outside_diff_is_listed(self):
        f = dict(finding(), file='other.py', suggestion='s = """```"""')
        p = self.build([f], 'ship-after-fixes')
        self.assertEqual(p['comments'], [])
        self.assertIn('Outside the lines this PR changed (1)', p['body'])
        self.assertIn('````python\ns = """```"""\n````', p['body'])
        self.assertEqual(post_review.fence('a ``` b'), '````\na ``` b\n````')

    def test_endorsed_authors_are_not_pinged(self):
        d = dict(review(), endorsed_comments=[dict(author='alice', where='code.py:1', why='right')])
        self.package(d)
        payload, _ = post_review.build(self.pkg)
        self.assertIn('`@alice`', payload['body'])
        self.assertIn('✅ Looks good to merge', payload['body'])


if __name__ == '__main__':
    unittest.main()
