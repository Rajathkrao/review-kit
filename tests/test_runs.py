"""Run folders in <repo>/.review-kit, resumable state, and temporary source worktrees."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(os.environ.get('RK_TEST_SCRIPTS', ROOT / 'skills/review-kit/scripts'))


def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, check=True, text=True, capture_output=True).stdout.strip()


class RunFolders(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / 'home'
        self.home.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home)}  # isolate ~/.review-kit/config.json
        self.repo = Path(tmp.name) / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-b', 'main')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        git(self.repo, 'config', 'user.name', 'Test')
        (self.repo / 'code.py').write_text('value = 1\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'Initial')
        self.first = git(self.repo, 'rev-parse', 'HEAD')
        git(self.repo, 'checkout', '-b', 'feature')
        (self.repo / 'code.py').write_text('value = 2\n')
        git(self.repo, 'commit', '-am', 'Change value')
        self.second = git(self.repo, 'rev-parse', 'HEAD')

    def collect(self, *args, mode='deep'):
        r = subprocess.run([sys.executable, str(SCRIPTS / 'collect.py'), '--mode', mode, *args],
                           cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return Path(r.stdout.strip().splitlines()[-1])

    def state(self, *args):
        r = subprocess.run([sys.executable, str(SCRIPTS / 'state.py'), *map(str, args)],
                           cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def meta(self, pkg):
        return json.loads((pkg / 'meta.json').read_text())

    def worktrees(self):
        return git(self.repo, 'worktree', 'list', '--porcelain')

    def test_run_folder_lives_in_repo_and_stays_out_of_git(self):
        pkg = self.collect()
        self.assertEqual(pkg.parent, self.repo / '.review-kit' / 'runs')
        self.assertIn('-deep-', pkg.name)
        for f in ('summary.md', 'diff.patch', 'diff-numbered.txt', 'meta.json', 'state.json'):
            self.assertTrue((pkg / f).exists(), f)
        self.assertEqual(git(self.repo, 'status', '--porcelain', '--untracked-files=all'), '')
        exclude = (self.repo / '.git' / 'info' / 'exclude').read_text()
        self.assertIn('/.review-kit/', exclude.split())
        self.assertEqual((self.repo / '.review-kit' / 'latest').read_text().strip(),
                         str(pkg.relative_to(self.repo)))
        # A second run must not review the first run's files, even with the exclude line removed.
        (self.repo / '.git' / 'info' / 'exclude').write_text('')
        pkg2 = self.collect()
        self.assertNotIn('.review-kit', (pkg2 / 'diff.patch').read_text())
        self.assertNotEqual(pkg, pkg2)

    def test_state_tracks_stages_and_lists_runs(self):
        pkg = self.collect()
        st = json.loads((pkg / 'state.json').read_text())
        self.assertEqual((st['stages_done'], st['next']), (['packaged'], 'contract'))
        self.state(pkg, 'packaged', '--args', 'deep --html')
        self.state(pkg, 'contract', '--note', 'ADR-7')
        self.state(pkg, 'lenses')
        listing = self.state('--list', self.repo)
        self.assertIn('next=tests', listing)
        self.assertIn("args='deep --html'", listing)
        st = json.loads((pkg / 'state.json').read_text())
        self.assertEqual(st['stages_done'], ['packaged', 'contract', 'lenses'])
        self.assertIn('contract: ADR-7', st['notes'])
        # Skipping an optional stage (tests) must still leave a reported run complete.
        self.state(pkg, 'verified')
        self.assertEqual(json.loads((pkg / 'state.json').read_text())['next'], 'reported')
        self.state(pkg, 'reported')
        self.assertIsNone(json.loads((pkg / 'state.json').read_text())['next'])
        self.assertIn('next=complete', self.state('--list', self.repo))

    def test_no_copy_when_checkout_is_already_the_reviewed_commit(self):
        pkg = self.collect('--target', self.second)
        meta = self.meta(pkg)
        self.assertEqual(meta['source_kind'], 'checkout-at-reviewed-commit')
        self.assertEqual(Path(meta['repo_root']).resolve(), self.repo.resolve())
        self.assertNotIn('review-kit/worktrees', self.worktrees())

    def test_dirty_checkout_or_other_commit_gets_a_temporary_worktree_outside_the_tree(self):
        (self.repo / 'code.py').write_text('value = 3\n')  # uncommitted edit at the same commit
        pkg = self.collect('--target', self.second)
        meta = self.meta(pkg)
        self.assertEqual(meta['source_kind'], 'pinned-worktree')
        src = Path(meta['repo_root'])
        self.assertEqual((src / 'code.py').read_text(), 'value = 2\n')
        self.assertEqual((self.repo / 'code.py').read_text(), 'value = 3\n')
        self.assertIn(Path(git(self.repo, 'rev-parse', '--absolute-git-dir')) / 'review-kit' / 'worktrees',
                      src.parents)
        self.assertEqual(src.resolve().relative_to(self.repo.resolve()).parts[0], '.git')
        # Finishing the run removes the copy and its registration.
        out = self.state(pkg, 'reported')
        self.assertIn('removed', out)
        self.assertFalse(src.exists())
        self.assertNotIn(str(src), self.worktrees())
        self.assertTrue(self.meta(pkg)['source_removed'])

    def test_keep_source_and_dirty_copies_are_kept(self):
        (self.repo / '.review-kit').mkdir()
        (self.repo / '.review-kit' / 'config.json').write_text('{"keep_source": true}')
        pkg = self.collect('--target', self.first)
        src = Path(self.meta(pkg)['repo_root'])
        self.state(pkg, 'reported')
        self.assertTrue(src.exists())
        (self.repo / '.review-kit' / 'config.json').write_text('{}')
        pkg2 = self.collect('--target', self.first)
        src2 = Path(self.meta(pkg2)['repo_root'])
        (src2 / 'code.py').write_text('edited in the copy\n')
        out = self.state(pkg2, 'reported')
        self.assertIn('kept', out)
        self.assertTrue(src2.exists())

    def test_cleanup_prunes_old_runs_and_stale_copies(self):
        (self.repo / '.review-kit').mkdir()
        (self.repo / '.review-kit' / 'config.json').write_text('{"keep_runs": 1}')
        finished = [self.collect('--target', self.first) for _ in range(2)]
        for pkg in finished:
            self.state(pkg, 'reported')
        stale = self.collect('--target', self.first)  # interrupted: never reported
        stale_src = Path(self.meta(stale)['repo_root'])
        old = time.time() - 2 * 86400
        os.utime(stale, (old, old))
        os.utime(stale / 'state.json', (old, old))
        self.collect()  # next run cleans up
        self.assertFalse(finished[0].exists())
        self.assertTrue(self.meta(finished[1])['source_removed'])
        self.assertTrue(stale.exists())  # unfinished runs are kept for /rk:resume
        self.assertFalse(stale_src.exists())
        self.assertNotIn('review-kit/worktrees', self.worktrees())

    def test_html_is_written_only_in_the_run_folder(self):
        pkg = self.collect()
        (pkg / 'findings.json').write_text(json.dumps(dict(
            execution_status='completed', verdict='ship', summary='Nothing material', findings=[])))
        r = subprocess.run([sys.executable, str(SCRIPTS / 'render_html.py'), str(pkg)],
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Path(r.stdout.strip()), pkg / 'review.html')
        self.assertFalse((self.home / '.review-kit' / 'reports').exists())

    def test_next_run_preserves_dirty_source_and_its_metadata(self):
        (self.repo / '.review-kit').mkdir()
        (self.repo / '.review-kit' / 'config.json').write_text('{"keep_runs": 0}')
        pkg = self.collect('--target', self.first)
        src = Path(self.meta(pkg)['repo_root'])
        (src / 'code.py').write_text('valuable edit\n')
        (src / 'notes.txt').write_text('valuable untracked file\n')
        self.state(pkg, 'reported')
        self.collect()
        self.assertEqual((src / 'code.py').read_text(), 'valuable edit\n')
        self.assertEqual((src / 'notes.txt').read_text(), 'valuable untracked file\n')
        self.assertTrue((pkg / 'meta.json').exists())
        self.assertFalse(self.meta(pkg).get('source_removed', False))

    def test_next_run_honors_keep_source_even_past_retention(self):
        (self.repo / '.review-kit').mkdir()
        (self.repo / '.review-kit' / 'config.json').write_text('{"keep_source": true, "keep_runs": 0}')
        pkg = self.collect('--target', self.first)
        src = Path(self.meta(pkg)['repo_root'])
        self.state(pkg, 'reported')
        self.collect()
        self.assertTrue(src.exists())
        self.assertTrue((pkg / 'meta.json').exists())

    def test_recent_progress_prevents_stale_source_cleanup(self):
        pkg = self.collect('--target', self.first)
        src = Path(self.meta(pkg)['repo_root'])
        old = time.time() - 2 * 86400
        os.utime(pkg, (old, old))
        self.state(pkg, 'contract', '--note', 'active now')
        self.collect()
        self.assertTrue(src.exists())

    def test_untracked_source_requires_isolation_for_committed_review(self):
        (self.repo / 'CLAUDE.md').write_text('uncommitted instructions\n')
        pkg = self.collect('--target', self.second)
        meta = self.meta(pkg)
        self.assertEqual(meta['source_kind'], 'pinned-worktree')
        self.assertFalse((Path(meta['repo_root']) / 'CLAUDE.md').exists())
        self.assertEqual((self.repo / 'CLAUDE.md').read_text(), 'uncommitted instructions\n')

    def test_resume_checks_reused_checkout_before_reusing_results(self):
        pkg = self.collect('--target', self.second)
        self.state('--check-source', pkg)
        for change in ('branch', 'tracked', 'untracked'):
            with self.subTest(change=change):
                if change == 'branch':
                    git(self.repo, 'checkout', 'main')
                elif change == 'tracked':
                    (self.repo / 'code.py').write_text('changed after collection\n')
                else:
                    (self.repo / 'new.py').write_text('untracked = True\n')
                r = subprocess.run([sys.executable, str(SCRIPTS / 'state.py'), '--check-source', str(pkg)],
                                   env=self.env, text=True, capture_output=True)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('fresh run', r.stderr)
                git(self.repo, 'checkout', 'feature')
                git(self.repo, 'checkout', '--', 'code.py')

    def test_resume_checks_pinned_source_and_missing_source(self):
        pkg = self.collect('--target', self.first)
        self.state('--check-source', pkg)
        self.state(pkg, 'reported')
        r = subprocess.run([sys.executable, str(SCRIPTS / 'state.py'), '--check-source', str(pkg)],
                           env=self.env, text=True, capture_output=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('fresh run', r.stderr)


if __name__ == '__main__':
    unittest.main()
