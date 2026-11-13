"""The one-call context command: nothing in the repo, everything printed, Python hints."""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from test_reliability import TemporaryCase, SCRIPTS, git
import collect


SERVICE = '''import time
from datetime import datetime


def split(amount, n, tags=[]):
    return [amount / n for _ in range(n)]


async def run():
    time.sleep(1)
    return datetime.now()
'''


class ContextTests(TemporaryCase):
    def branch_with_python_change(self):
        git(self.repo, 'checkout', '-q', '-b', 'feature')
        (self.repo / 'svc.py').write_text(SERVICE)
        (self.repo / 'use.py').write_text('from svc import split\n\nprint(split(10, 3))\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'Add split')

    def test_prints_everything_and_writes_nothing_in_the_repo(self):
        self.branch_with_python_change()
        r = self.collector('--base', 'main')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(git(self.repo, 'status', '--porcelain', '--untracked-files=all'), '')
        self.assertFalse((self.repo / '.review-kit').exists())
        self.assertIn(f'PKG={self.pkg}', r.stdout.splitlines()[-1])
        self.assertIn('## Numbered diff', r.stdout)
        self.assertIn('     5 +def split(amount, n, tags=[]):', r.stdout)
        self.assertIn('split: use.py:3', r.stdout)
        meta = json.loads((self.pkg / 'meta.json').read_text())
        self.assertIn('concurrency', meta['risk'])
        self.assertEqual(meta['suggested_depth'], 'quick')

    @unittest.skipUnless(shutil.which('ruff'), 'ruff not installed')
    def test_ruff_hints_only_for_added_lines(self):
        (self.repo / 'old.py').write_text('def f(x=[]):\n    return x\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'Pre-existing mutable default')
        self.branch_with_python_change()
        r = self.collector('--base', 'main')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('svc.py:5 B006', r.stdout)
        self.assertIn('svc.py:10 ASYNC251', r.stdout)
        self.assertIn('svc.py:11 DTZ005', r.stdout)
        self.assertNotIn('old.py', r.stdout.split('## Static hints', 1)[1].split('##', 1)[0])

    def test_learnings_are_printed(self):
        self.branch_with_python_change()
        (self.repo / '.review-kit').mkdir()
        (self.repo / '.review-kit/learnings.md').write_text('- Do not flag print() in scripts.\n')
        r = self.collector('--base', 'main')
        self.assertIn('Do not flag print() in scripts.', r.stdout)
        self.assertNotIn('.review-kit/learnings.md (+', r.stdout)  # never reviewed as a change

    def test_large_diff_is_not_inlined(self):
        git(self.repo, 'checkout', '-q', '-b', 'big')
        (self.repo / 'big.py').write_text(''.join(f'x{i} = {i}\n' for i in range(2000)))
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'Big')
        r = self.collector('--base', 'main')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('## Numbered diff', r.stdout)
        self.assertIn('read it in parts', r.stdout)
        self.assertEqual(json.loads((self.pkg / 'meta.json').read_text())['suggested_depth'], 'deep')

    def test_pinned_copy_lives_in_pkg_and_done_removes_it(self):
        (self.repo / 'code.py').write_text('value = 2\n')
        git(self.repo, 'commit', '-qam', 'Change')
        head = git(self.repo, 'rev-parse', 'HEAD')
        (self.repo / 'code.py').write_text('value = 3\n')  # dirty checkout forces a copy
        r = self.collector('--target', head)
        self.assertEqual(r.returncode, 0, r.stderr)
        meta = json.loads((self.pkg / 'meta.json').read_text())
        self.assertEqual(meta['source_kind'], 'pinned-copy')
        self.assertEqual(Path(meta['repo_root']), self.pkg / 'src')
        self.assertEqual((self.pkg / 'src/code.py').read_text(), 'value = 2\n')
        done = subprocess.run([sys.executable, str(SCRIPTS / 'collect.py'), '--done', str(self.pkg)],
                              cwd=self.repo, capture_output=True, text=True)
        self.assertIn('removed', done.stdout)
        self.assertFalse((self.pkg / 'src').exists())
        self.assertEqual((self.repo / 'code.py').read_text(), 'value = 3\n')

    def test_default_scratch_folder_is_outside_the_repo(self):
        self.branch_with_python_change()
        env = {**self.env, 'RK_SCRATCH': str(self.root / 'scratch')}
        r = subprocess.run([sys.executable, str(SCRIPTS / 'collect.py'), '--base', 'main'],
                           cwd=self.repo, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        pkg = Path(r.stdout.splitlines()[-1].split('=', 1)[1])
        self.assertEqual(pkg.parent, self.root / 'scratch')
        self.assertTrue((pkg / 'diff-numbered.txt').is_file())

    def test_depth_suggestion(self):
        files = [{'path': 'a.py'}]
        self.assertEqual(collect.suggest_depth(50, ['money', 'concurrency'], files)[0], 'quick')
        self.assertEqual(collect.suggest_depth(200, ['money', 'concurrency'], files)[0], 'deep')
        self.assertEqual(collect.suggest_depth(500, [], files)[0], 'deep')


if __name__ == '__main__':
    unittest.main()
