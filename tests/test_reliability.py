"""Regression tests; isolated Git repositories and fake CLIs, no network or model access."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(os.environ.get('RK_TEST_SCRIPTS', ROOT / 'skills/review-kit/scripts'))
sys.path.insert(0, str(SCRIPTS))
import collect
import post_review
import render_html
import review_data


def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, check=True, text=True, capture_output=True).stdout.strip()


def repository(root):
    root.mkdir()
    git(root, 'init', '-b', 'main')
    git(root, 'config', 'user.email', 'test@example.invalid')
    git(root, 'config', 'user.name', 'Test')
    (root / 'code.py').write_text('value = 1\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'Initial')
    return git(root, 'rev-parse', 'HEAD')


def finding():
    return dict(title='Confirmed defect', body='Failure path', file='code.py', line_start=1,
                line_end=1, severity='important', confidence=95, recommendation='Add guard',
                evidence='Read guard and callers', evidence_status='source-verified')


def review(findings=None, status='completed'):
    findings = [] if findings is None else findings
    verdict = 'ship-after-fixes' if findings else 'ship'
    return dict(execution_status=status, verdict=verdict if status=='completed' else 'inconclusive',
                summary='Review evidence', findings=findings)


class TemporaryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.base = repository(self.repo)
        self.pkg = self.root / 'pkg'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH']}

    def cli(self, name, body):
        p = self.bin / name
        p.write_text('#!' + sys.executable + '\n' + body)
        p.chmod(0o755)

    def collector(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / 'collect.py'), '--out', str(self.pkg), *args],
                              cwd=self.repo, env=self.env, capture_output=True, text=True)

    def package(self, data=None):
        self.pkg.mkdir(exist_ok=True)
        (self.pkg / 'meta.json').write_text(json.dumps(dict(repo='test', description='Test',
            collection_status='completed', reviewed_commit=self.base, repo_root=str(self.repo),
            github=dict(owner='owner', repo='repo', pr=1), files=[])))
        (self.pkg / 'findings.json').write_text(json.dumps(review() if data is None else data))
        (self.pkg / 'pr.json').write_text(json.dumps(dict(headRefOid=self.base)))
        (self.pkg / 'diff.patch').write_text('')
        (self.pkg / 'candidates').mkdir(exist_ok=True)


class CollectorTests(TemporaryCase):
    def test_invalid_ranges_fail(self):
        for target in ['missing..HEAD', 'HEAD...missing', 'HEAD..HEAD..HEAD']:
            with self.subTest(target=target):
                self.assertNotEqual(self.collector('--target', target).returncode, 0)
                shutil.rmtree(self.pkg)

    def test_root_commit_has_diff_and_pinned_source(self):
        r = self.collector('--target', self.base)
        self.assertEqual(r.returncode, 0, r.stderr)
        meta = json.loads((self.pkg/'meta.json').read_text())
        self.assertEqual(meta['reviewed_commit'], self.base)
        self.assertEqual(meta['size'], 'ok')
        self.assertNotEqual(meta['repo_root'], str(self.repo))
        self.assertEqual((Path(meta['repo_root'])/'code.py').read_text(), 'value = 1\n')

    def test_historical_range_preserves_dirty_checkout(self):
        (self.repo/'code.py').write_text('value = 2\n')
        git(self.repo, 'commit', '-am', 'Change')
        head = git(self.repo, 'rev-parse', 'HEAD')
        (self.repo/'code.py').write_text('value = 3\n')
        before = git(self.repo, 'status', '--porcelain')
        r = self.collector('--target', self.base + '..' + head)
        self.assertEqual(r.returncode, 0, r.stderr)
        meta = json.loads((self.pkg/'meta.json').read_text())
        self.assertEqual((Path(meta['repo_root'])/'code.py').read_text(), 'value = 2\n')
        self.assertEqual(git(self.repo, 'status', '--porcelain'), before)
        self.assertEqual((self.repo/'code.py').read_text(), 'value = 3\n')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), head)

    def test_invalid_explicit_base_fails(self):
        self.assertNotEqual(self.collector('--base', 'missing').returncode, 0)

    def test_local_changes_and_untracked_are_included(self):
        (self.repo/'code.py').write_text('value = 2\n')
        (self.repo/'new.py').write_text('new = 1\n')
        r=self.collector()
        self.assertEqual(r.returncode, 0, r.stderr)
        meta=json.loads((self.pkg/'meta.json').read_text())
        self.assertEqual(meta['source_kind'], 'working-tree')
        self.assertEqual({f['path'] for f in meta['files']}, {'code.py','new.py'})

    def test_empty_valid_diff_and_stale_package(self):
        r=self.collector('--target', 'HEAD..HEAD')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((self.pkg/'meta.json').read_text())['size'], 'empty')
        self.assertNotEqual(self.collector('--target', 'HEAD..HEAD').returncode, 0)

    def test_diff_hunk_lines_that_look_like_headers(self):
        diff='diff --git a/c.js b/c.js\n--- a/c.js\n+++ b/c.js\n@@ -1,2 +1,3 @@\n let x = 0;\n+++x;\n report(x);\n'
        self.assertIn('     2 +++x;', collect.numbered_diff(diff))
        self.assertIn('     3  report(x);', collect.numbered_diff(diff))
        self.assertEqual(collect.numstat(diff)[0]['added'], 1)

    def test_pr_diff_failure_is_not_empty_success(self):
        self.pkg.mkdir()
        (self.repo/'code.py').write_text('value = 2\n');git(self.repo,'commit','-am','Change')
        head=git(self.repo,'rev-parse','HEAD')
        pr=dict(baseRefOid=self.base,headRefOid=head,commits=[],title='Change')
        real=collect.run
        def run(cmd, **kwargs):
            if cmd[0]=='gh':
                if kwargs.get('check'): raise RuntimeError('diff retrieval failed')
                return subprocess.CompletedProcess(cmd, 1, '', 'diff retrieval failed')
            return real(cmd, **kwargs)
        with mock.patch.object(collect,'gh_json',return_value=(pr,None)), mock.patch.object(collect,'run',side_effect=run):
            with self.assertRaises((RuntimeError,SystemExit)):
                collect.collect_pr(str(self.repo),'1','owner/repo',self.pkg)

    def test_pr_source_is_pinned_and_incomplete_context_is_partial(self):
        (self.repo/'code.py').write_text('value = 2\n');git(self.repo,'commit','-am','PR change')
        head=git(self.repo,'rev-parse','HEAD')
        raw=git(self.repo,'diff',self.base,head)
        (self.repo/'code.py').write_text('value = 3\n')
        self.cli('gh', """import sys,os,json
args=sys.argv[1:]
info=json.loads(os.environ['PR_INFO'])
if args[:2]==['pr','view']:
 print(json.dumps(info));sys.exit(0)
if args[:2]==['pr','diff']:
 print(os.environ['PR_DIFF']);sys.exit(0)
if 'graphql' in args:
 if os.environ.get('NO_GRAPHQL'):sys.exit(1)
 print(json.dumps({'data':{'repository':{'pullRequest':{'reviewThreads':{'nodes':[]},'reviews':{'nodes':[]}}}}}));sys.exit(0)
print('[]')
""")
        self.env.update(PR_INFO=json.dumps(dict(baseRefOid=self.base,headRefOid=head,
            title='PR',commits=[])),PR_DIFF=raw)
        for fallback in ['', '1']:
            with self.subTest(fallback=fallback):
                self.pkg=self.root/('fallback' if fallback else 'complete')
                self.env['NO_GRAPHQL']=fallback
                r=self.collector('--target','https://github.com/owner/repo/pull/1')
                self.assertEqual(r.returncode,0,r.stderr)
                meta=json.loads((self.pkg/'meta.json').read_text())
                self.assertEqual(meta['collection_status'],'partial' if fallback else 'completed')
                self.assertEqual(meta['reviewed_commit'],head)
                self.assertEqual((Path(meta['repo_root'])/'code.py').read_text(),'value = 2\n')
                self.assertEqual((self.repo/'code.py').read_text(),'value = 3\n')

    def test_checked_timeout_propagates(self):
        with mock.patch.object(collect.subprocess,'run',side_effect=subprocess.TimeoutExpired('git',1)):
            with self.assertRaises(RuntimeError): collect.run(['git'],check=True)


class OutputTests(TemporaryCase):
    def render(self):
        with mock.patch.object(Path,'home',return_value=self.root): render_html.render(self.pkg)
        return (self.pkg/'review.html').read_text()

    def test_validator_cli_reports_success_and_failure(self):
        self.package()
        command=[sys.executable,str(SCRIPTS/'review_data.py'),str(self.pkg)]
        r=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('Review valid: completed',r.stdout)
        (self.pkg/'findings.json').write_text('{}')
        self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)

    def test_valid_empty_html(self):
        self.package()
        self.assertIn('No issues found.',self.render())

    def test_valid_finding_html_escapes_markup(self):
        f=finding();f['title']='<img src=x onerror=alert(1)>'
        self.package(review([f]))
        html=self.render()
        self.assertIn('&lt;img',html)
        self.assertNotIn('<img src=x',html)
        self.assertIn('source-verified',html)
        self.assertIn(self.base,html)

    def test_missing_malformed_or_wrong_shape_is_not_clean(self):
        self.package()
        for text in ['', '{bad', '[]', '{}', '{"findings": []}']:
            with self.subTest(text=text):
                (self.pkg/'findings.json').write_text(text)
                with self.assertRaises(ValueError): self.render()
        (self.pkg/'findings.json').unlink()
        with self.assertRaises(ValueError): self.render()

    def test_partial_failed_and_empty_scope_are_inconclusive(self):
        for status in ['partial','failed','nothing-to-review']:
            with self.subTest(status=status):
                self.package(review(status=status))
                html=self.render()
                self.assertNotIn('No issues found.',html)
                self.assertIn('No clean conclusion',html)
                with self.assertRaises(ValueError): post_review.build(self.pkg)

    def test_invalid_evidence_and_contradictory_verdict_fail(self):
        for field,value in [('line_start',0),('line_end',0),('confidence',float('nan')),
                            ('confidence',True),('evidence_status','guessed')]:
            with self.subTest(field=field):
                f=finding();f[field]=value
                with self.assertRaises(ValueError): review_data.validate_review(review([f]))
        for status in ['unverified']:
            f=finding();f['evidence_status']=status
            with self.assertRaises(ValueError): review_data.validate_review(review([f]))
        d=review([finding()]);d['verdict']='ship'
        with self.assertRaises(ValueError):review_data.validate_review(d)

    def test_partial_collection_cannot_be_completed(self):
        with self.assertRaises(ValueError):
            review_data.validate_review(review(),{'collection_status':'partial'})

    def test_collected_empty_scope_cannot_claim_clean_review(self):
        with self.assertRaises(ValueError):
            review_data.validate_review(review(),{'collection_status':'completed','size':'empty'})
        review_data.validate_review(review(status='nothing-to-review'),{'size':'empty'})

    def test_test_reproduction_requires_execution_evidence(self):
        f=finding();f['evidence_status']='test-reproduced'
        with self.assertRaises(ValueError):review_data.validate_review(review([f]))
        f['test_evidence']=dict(command='python probe.py',exit_code=1,
            observed='Assertion proves the missing guard',setup_succeeded=True,target_exercised=False)
        with self.assertRaises(ValueError):review_data.validate_review(review([f]))
        f['test_evidence']['target_exercised']=True
        review_data.validate_review(review([f]))

    def test_posting_preflight_fails_closed(self):
        self.package()
        sentinel=self.root/'posted'
        self.env['SENTINEL']=str(sentinel)
        self.cli('gh', '''import sys,os
from pathlib import Path
if sys.argv[1:3]==['pr','view']:
 print(os.environ.get('GH_RESPONSE',''))
 sys.exit(int(os.environ.get('GH_EXIT','0')))
Path(os.environ['SENTINEL']).write_text('posted')
print('{}')
''')
        for code,data in [(1,''),(0,''),(0,'{bad'),(0,'[]'),(0,'{}'),
                          (0,json.dumps(dict(headRefOid='wrong',state='OPEN'))),
                          (0,json.dumps(dict(headRefOid=self.base,state='CLOSED')))]:
            for flags in [['--submit'],['--reply','12','--body-file',str(self.pkg/'findings.json')]]:
                with self.subTest(code=code,data=data,flags=flags):
                    env={**self.env,'GH_EXIT':str(code),'GH_RESPONSE':data}
                    r=subprocess.run([sys.executable,str(SCRIPTS/'post_review.py'),str(self.pkg),*flags],env=env,capture_output=True)
                    self.assertNotEqual(r.returncode,0)
                    self.assertFalse(sentinel.exists())
        self.env['GH_RESPONSE']=json.dumps(dict(headRefOid=self.base,state='OPEN'))
        r=subprocess.run([sys.executable,str(SCRIPTS/'post_review.py'),str(self.pkg),'--submit'],env=self.env,capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue(sentinel.exists())


class CLITests(TemporaryCase):
    def test_codex_wrapper_rejects_invalid_and_accepts_valid(self):
        self.package()
        self.cli('codex', '''import sys,os,json
from pathlib import Path
if sys.argv[1] in ['--version','login']: sys.exit(0)
if os.environ.get('SCHEMA_FALLBACK') and '--output-schema' in sys.argv:
 print("unexpected argument '--output-schema'",file=sys.stderr);sys.exit(1)
if os.environ.get('CODEX_FAIL'): sys.exit(1)
Path(sys.argv[sys.argv.index('-o')+1]).write_text(os.environ['CODEX_OUTPUT'])
''')
        good=dict(verdict='approve',summary='No material issue',findings=[],next_steps=[])
        for raw in ['No bugs found','{}','[]',json.dumps({**good,'findings':'none'}),
                    json.dumps({**good,'verdict':'unknown'})]:
            with self.subTest(raw=raw):
                (self.pkg/'candidates/second-model.json').write_text('stale')
                env={**self.env,'CODEX_OUTPUT':raw,'SCHEMA_FALLBACK':'1'}
                r=subprocess.run(['bash',str(SCRIPTS/'codex_review.sh'),str(self.pkg)],env=env,capture_output=True)
                self.assertNotEqual(r.returncode,0)
                self.assertFalse((self.pkg/'candidates/second-model.json').exists())
        for fallback in ['', '1']:
            env={**self.env,'CODEX_OUTPUT':json.dumps(good),'SCHEMA_FALLBACK':fallback}
            r=subprocess.run(['bash',str(SCRIPTS/'codex_review.sh'),str(self.pkg)],env=env,capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(json.loads((self.pkg/'second-model-status.json').read_text())['execution_status'],'completed')

    def test_eval_setup_and_model_failures_cannot_succeed(self):
        here=self.root/'evals';here.mkdir()
        shutil.copy(ROOT/'evals/run_case.sh',here/'run_case.sh')
        (here/'fixtures').mkdir();shutil.copytree(self.repo,here/'fixtures/demo')
        self.cli('claude', '''import sys,os,json
if '--version' in sys.argv:print('fake-claude');sys.exit(0)
sys.exit(int(os.environ.get('MODEL_EXIT','0'))) if os.environ.get('MODEL_EXIT') else None
print(os.environ.get('MODEL_RESULT',''))
''')
        cases=[('bad-branch','missing','',0),('failed-model','main','',1),
               ('missing-result','main','{}',0),('empty-result','main',json.dumps(dict(type='result',subtype='success',is_error=False,result='')),0),
               ('errored-result','main',json.dumps(dict(type='result',subtype='error',is_error=True,result='failure')),0),
               ('valid','main',json.dumps(dict(type='result',subtype='success',is_error=False,result='No issues found.')),0)]
        for name,branch,result,exit_code in cases:
            with self.subTest(name=name):
                env={**self.env,'MODEL_RESULT':result,'MODEL_EXIT':str(exit_code) if exit_code else ''}
                r=subprocess.run(['bash',str(here/'run_case.sh'),'demo',branch,name,'/rk:deep'],env=env,capture_output=True)
                status=json.loads((here/'runs'/name/'status.json').read_text())
                self.assertEqual(r.returncode==0,name=='valid',r.stderr)
                self.assertEqual(status['execution_status'],'completed' if name=='valid' else 'failed')
                self.assertEqual((here/'runs'/name/'report.md').exists(),name=='valid')


if __name__=='__main__':unittest.main()
