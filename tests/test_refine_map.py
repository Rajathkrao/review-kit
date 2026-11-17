"""Refine mode's structure map: measured leads, a scoreboard, and a before/after comparison."""
import json
import subprocess
import sys

from test_reliability import TemporaryCase, SCRIPTS, git
import refine_map

FEES = '''import time

RATE_URL = "https://rates.example.com/v1"


def fee(plan, amount, skip=False):
    if skip:
        return 0
    if plan == "gold":
        return amount * 0.01
    return amount * 0.02


def fee_wrapper(plan, amount):
    return fee(plan, amount)


def load(path):
    try:
        return open(path).read()
    except OSError:
        pass


def wait():
    time.sleep(2)  # HACK: the bank API is slow


def orphan_helper(x):
    return x + 1


def total_orders(rows):
    total = 0
    for row in rows:
        if row.ok:
            total += row.amount
    return total
'''
REPORT = '''from pkg.fees import fee

RATE_URL = "https://rates.example.com/v1"


class Base:
    pass


class Only(Base):
    pass


def total_refunds(items):
    acc = 0
    for item in items:
        if item.valid:
            acc += item.value
    return acc


def run(plan, amount):
    return fee(plan, amount)
'''


class RefineMapTests(TemporaryCase):
    def setUp(self):
        super().setUp()
        (self.repo / 'pkg').mkdir()
        (self.repo / 'pkg/__init__.py').write_text('')
        (self.repo / 'pkg/fees.py').write_text(FEES)
        (self.repo / 'pkg/report.py').write_text(REPORT)
        (self.repo / 'rates.py').write_text('X = 1\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'Package')
        for i in range(3):  # fees.py and rates.py keep changing together, with no import between them
            (self.repo / 'pkg/fees.py').write_text(FEES + f'\n# rev {i}\n')
            (self.repo / 'rates.py').write_text(f'X = {i + 2}\n')
            git(self.repo, 'commit', '-qam', f'Rates {i}')
        self.map = refine_map.build(self.repo, ['pkg'])
        self.text = refine_map.render(self.map)

    def kinds(self):
        return {kind for _, _, kind, _ in self.map['special']}

    def test_special_cases_are_found_and_counted(self):
        self.assertLessEqual({'swallowed exception', 'sleep', 'flag parameter', 'one-value branch', 'workaround note'},
                             self.kinds())
        self.assertEqual(self.map['score']['special_cases'], len(self.map['special']))
        self.assertIn("pkg/fees.py:9 one-value branch: if … 'gold'", self.text)

    def test_wrappers_copies_and_lone_base_classes(self):
        self.assertEqual([(f, name) for f, name, _, _ in self.map['pass_through']],
                         [('pkg/fees.py', 'fee_wrapper'), ('pkg/report.py', 'run')])
        self.assertEqual(len(self.map['copies']), 1)
        self.assertIn('total_orders()', self.map['copies'][0][0] + self.map['copies'][0][1])
        self.assertIn('total_refunds()', self.map['copies'][0][0] + self.map['copies'][0][1])
        self.assertIn('Base has one subclass (Only)', self.text)

    def test_repeated_literal_and_unmentioned_name(self):
        self.assertIn("'https://rates.example.com/v1'", [v for v, _ in self.map['repeated']])
        self.assertIn('orphan_helper', [name for name, _ in self.map['unused']])
        self.assertNotIn('fee', [name for name, _ in self.map['unused']])

    def test_imports_and_history(self):
        self.assertEqual(self.map['graph']['pkg/report.py'], {'pkg/fees.py'})
        self.assertEqual(self.map['fan_in']['pkg/fees.py'], 1)
        self.assertEqual(self.map['churn']['pkg/fees.py'], 4)
        self.assertIn(('pkg/fees.py', 'rates.py'), [(a, b) for a, b, _, _ in self.map['linked']])
        self.assertIn('pkg/fees.py and rates.py: together in 4', self.text)

    def test_cycle_is_reported(self):
        (self.repo / 'pkg/fees.py').write_text('from pkg import report\n' + FEES)
        m = refine_map.build(self.repo, ['pkg'])
        self.assertEqual(m['score']['cycles'], 1)
        self.assertIn('CYCLE:', refine_map.render(m))

    def test_broken_and_non_python_files_do_not_stop_the_map(self):
        (self.repo / 'pkg/bad.py').write_text('def broken(:\n')
        (self.repo / 'pkg/app.ts').write_text('export const a = 1\n')
        m = refine_map.build(self.repo, ['pkg'])
        self.assertEqual(m['unparsed'], ['pkg/bad.py'])
        self.assertIn('1 non-Python files', refine_map.render(m))

    def test_compare_shows_what_a_refactor_removed(self):
        before = self.root / 'before.json'
        cmd = [sys.executable, str(SCRIPTS / 'refine_map.py'), '--root', str(self.repo)]
        r = subprocess.run(cmd + ['pkg', '--json', str(before)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(before.read_text())['paths'], ['pkg'])
        (self.repo / 'pkg/fees.py').write_text(FEES.split('def fee_wrapper')[0])
        r = subprocess.run(cmd + ['--compare', str(before)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('| Pass-through wrappers | 2 | 1 | -1 |', r.stdout)
        self.assertRegex(r.stdout, r'\| Special cases \| 5 \| 2 \| -3 \|')

    def test_collector_prints_the_map_and_saves_the_baseline_in_refine_mode(self):
        r = self.collector('--mode', 'refine', '--whole', '--target', 'pkg')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('## Structure map', r.stdout)
        self.assertIn('fee_wrapper() only forwards its arguments to fee()', r.stdout)
        saved = json.loads((self.pkg / 'refine-before.json').read_text())
        self.assertEqual(saved['paths'], ['pkg/__init__.py', 'pkg/fees.py', 'pkg/report.py'])
        self.assertEqual(git(self.repo, 'status', '--porcelain', '--untracked-files=all'), '')
        self.assertNotIn('## Structure map', self.collector('--mode', 'quick', '--whole', '--target', 'pkg',
                                                             '--out', str(self.root / 'other')).stdout)
