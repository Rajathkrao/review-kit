"""Failure/retry/terminal transitions, exercised without model or GitHub access."""
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
sys.path.insert(0, str(SCRIPTS))
import state


class LifecycleTests(TemporaryCase):
    def run_state(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / 'state.py'),
                               *map(str, args)], env=self.env, capture_output=True, text=True)

    def test_corrupt_metadata_cannot_bypass_completion(self):
        self.package()
        for raw in ('{broken', '[]'):
            (self.pkg / 'meta.json').write_text(raw)
            result = self.run_state(self.pkg, 'reported')
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertFalse((self.pkg / 'state.json').exists())

    def test_completed_run_cannot_be_reopened_by_marking_an_earlier_stage(self):
        self.package()
        self.assertEqual(self.run_state(self.pkg, 'reported', '--force').returncode, 0)
        before = (self.pkg / 'state.json').read_bytes()
        result = self.run_state(self.pkg, 'contract')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.pkg / 'state.json').read_bytes(), before)

    def test_revisiting_contract_invalidates_downstream_results_and_resume_cache(self):
        self.package()
        (self.pkg / 'contract.md').write_text('Revised purpose')
        for stage in ('contract', 'lenses', 'verified'):
            self.assertEqual(self.run_state(self.pkg, stage).returncode, 0)
        for name in ('candidates/old.json', 'test-results.md', 'report.md', 'review.html',
                     'review-payload.json', 'candidates-merged.json'):
            (self.pkg / name).write_text('{}')
        self.assertEqual(self.run_state(self.pkg, 'contract').returncode, 0)
        self.assertEqual(state.load(self.pkg)['next'], 'lenses')
        self.assertEqual((self.pkg / 'contract.md').read_text(), 'Revised purpose')
        for name in ('candidates/old.json', 'findings.json', 'test-results.md', 'report.md',
                     'review.html', 'review-payload.json', 'candidates-merged.json'):
            self.assertFalse((self.pkg / name).exists(), name)

    def test_missing_state_is_incomplete_and_corrupt_state_is_rejected(self):
        self.package()
        self.assertEqual(state.load(self.pkg)['next'], 'packaged')
        for raw in ('[]', '{bad', '{"stages_done":"reported"}',
                    '{"stages_done":["unknown"]}'):
            (self.pkg / 'state.json').write_text(raw)
            result = self.run_state(self.pkg, 'contract')
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual((self.pkg / 'state.json').read_text(), raw)

    def test_completion_rejects_invalid_lens_output_and_requires_contract(self):
        self.package()
        meta = json.loads((self.pkg / 'meta.json').read_text())
        meta.update(mode='spec', config={'html': 'never'})
        (self.pkg / 'meta.json').write_text(json.dumps(meta))
        (self.pkg / 'report.md').write_text('Report')
        for raw in ('{bad', '[]', '{}', '{"candidates":"none"}'):
            (self.pkg / 'candidates/spec.json').write_text(raw)
            result = self.run_state(self.pkg, 'reported')
            self.assertNotEqual(result.returncode, 0, raw)
        (self.pkg / 'candidates/spec.json').write_text('{"candidates":[]}')
        self.assertNotEqual(self.run_state(self.pkg, 'reported').returncode, 0)
        (self.pkg / 'contract.md').write_text('Purpose: comply with the spec')
        self.assertEqual(self.run_state(self.pkg, 'reported').returncode, 0)

    def test_quick_pr_does_not_require_deep_lens_files(self):
        self.package()
        meta = json.loads((self.pkg / 'meta.json').read_text())
        meta.update(mode='pr', config={'html': 'never'})
        (self.pkg / 'meta.json').write_text(json.dumps(meta))
        (self.pkg / 'contract.md').write_text('Purpose')
        (self.pkg / 'report.md').write_text('Report')
        self.assertEqual(self.run_state(self.pkg, 'packaged', '--args', 'pr --quick').returncode, 0)
        result = self.run_state(self.pkg, 'reported')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_test_mode_requires_a_record_even_when_execution_is_declined(self):
        self.package()
        meta = json.loads((self.pkg / 'meta.json').read_text())
        meta.update(mode='test', config={'html': 'never'})
        (self.pkg / 'meta.json').write_text(json.dumps(meta))
        (self.pkg / 'contract.md').write_text('Purpose')
        (self.pkg / 'report.md').write_text('Report')
        (self.pkg / 'candidates/tests.json').write_text('{"candidates":[]}')
        result = self.run_state(self.pkg, 'reported')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('test-results.md', result.stderr)
        (self.pkg / 'test-results.md').write_text('Not run: user declined execution')
        self.assertEqual(self.run_state(self.pkg, 'reported').returncode, 0)

    def test_second_model_does_not_replace_a_required_lens(self):
        self.package()
        meta = json.loads((self.pkg / 'meta.json').read_text())
        meta.update(mode='spec', config={'html': 'never'})
        (self.pkg / 'meta.json').write_text(json.dumps(meta))
        (self.pkg / 'contract.md').write_text('Purpose')
        (self.pkg / 'report.md').write_text('Report')
        (self.pkg / 'candidates/second-model.json').write_text('{"candidates":[]}')
        result = self.run_state(self.pkg, 'reported')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('lens results: 0 of at least 1', result.stderr)

    def test_live_source_resume_rejects_head_tracked_and_untracked_changes(self):
        (self.repo / 'code.py').write_text('value = 2\n')
        self.assertEqual(self.collector().returncode, 0)
        self.assertEqual(self.run_state('--check-source', self.pkg).returncode, 0)
        (self.repo / 'code.py').write_text('value = 3\n')
        self.assertNotEqual(self.run_state('--check-source', self.pkg).returncode, 0)
        (self.repo / 'code.py').write_text('value = 2\n')
        (self.repo / 'new.py').write_text('new = 1\n')
        self.assertNotEqual(self.run_state('--check-source', self.pkg).returncode, 0)
        (self.repo / 'new.py').unlink()
        subprocess.run(['git', 'commit', '-am', 'Advance HEAD'], cwd=self.repo, check=True,
                       capture_output=True)
        self.assertNotEqual(self.run_state('--check-source', self.pkg).returncode, 0)

    def test_failed_collection_records_failure_not_missing_state(self):
        result = self.collector('--target', 'missing..HEAD')
        self.assertNotEqual(result.returncode, 0)
        meta = json.loads((self.pkg / 'meta.json').read_text())
        self.assertEqual(meta['collection_status'], 'failed')
        self.assertEqual(state.load(self.pkg)['next'], 'packaged')

    def test_custom_output_in_repo_is_not_reviewed_as_source(self):
        self.pkg = self.repo / 'review-output'
        (self.repo / 'code.py').write_text('value = 2\n')
        result = self.collector()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('review-output', (self.pkg / 'diff.patch').read_text())
        self.assertEqual(self.run_state('--check-source', self.pkg).returncode, 0)

    def test_rerender_after_source_changes_uses_saved_revision(self):
        (self.repo / 'code.py').write_text('value = 2\n')
        self.assertEqual(self.collector().returncode, 0)
        meta = json.loads((self.pkg / 'meta.json').read_text())
        self.assertEqual(render_html.Source(self.pkg, meta).lines('code.py')[0], 'value = 2')
        (self.repo / 'code.py').write_text('value = 99\n')
        self.assertEqual(render_html.Source(self.pkg, meta).lines('code.py')[0], 'value = 2')

    def test_cleanup_does_not_delete_runs_with_corrupt_state(self):
        self.assertEqual(self.collector().returncode, 0)
        runs = self.repo / '.review-kit/runs'
        runs.mkdir(parents=True)
        saved = runs / 'old-run'
        shutil.copytree(self.pkg, saved)
        (saved / 'state.json').write_text('{"stages_done":"reported"}')
        collect.cleanup_runs(str(self.repo), 0)
        self.assertTrue(saved.exists())


class BoundaryTests(TemporaryCase):
    def test_nonempty_scope_cannot_transition_to_nothing_to_review(self):
        with self.assertRaises(ValueError):
            review_data.validate_review(review(status='nothing-to-review'),
                                        {'size': 'ok', 'collection_status': 'completed'})

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
