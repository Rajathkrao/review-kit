"""The HTML walkthrough reads real source, pins problems on lines, and escapes model text."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(os.environ.get('RK_TEST_SCRIPTS', ROOT / 'skills/review-kit/scripts'))

SOURCE = "def charge(user):\n    total = price(user)\n    gateway.send(total)\n    return total\n"
DIFF = """diff --git a/pay.py b/pay.py
index 1111111..2222222 100644
--- a/pay.py
+++ b/pay.py
@@ -1,3 +1,4 @@
     1  def charge(user):
     2 +    total = price(user)
     3 +    gateway.send(total)
     4      return total
"""


class Walkthrough(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'src').mkdir()
        (self.root / 'src' / 'pay.py').write_text(SOURCE)
        self.pkg = self.root / 'pkg'
        self.pkg.mkdir()
        (self.pkg / 'meta.json').write_text(json.dumps(dict(
            repo='t', description='branch x', collection_status='completed', repo_root=str(self.root / 'src'),
            reviewed_commit='a' * 40, source_kind='working-tree', files=[{'path': 'pay.py', 'status': 'modified', 'added': 2, 'deleted': 0}])))
        (self.pkg / 'diff-numbered.txt').write_text(DIFF)
        finding = dict(id='F1', title='Charge sent twice <b>', body='Body', file='pay.py', line_start=1, line_end=4,
                       severity='critical', confidence=95, recommendation='Use a key', evidence='Read it',
                       evidence_status='source-verified')
        (self.pkg / 'findings.json').write_text(json.dumps(dict(
            execution_status='completed', verdict='dont-ship', summary='One problem', findings=[finding])))

    def render(self, explainer=None):
        if explainer is not None:
            (self.pkg / 'explainer.json').write_text(json.dumps(explainer))
        r = subprocess.run([sys.executable, str(SCRIPTS / 'render_html.py'), str(self.pkg)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return (self.pkg / 'review.html').read_text()

    def test_code_comes_from_source_with_changed_lines_and_pins(self):
        html = self.render(dict(
            title='Payments', steps=[dict(title='Charge', kind='logic', file='pay.py', lines=[1, 4],
                                          explanation='Explains', finding_ids=['F1'])],
            problems={'F1': dict(pin_line=3, line_note='Sent without a key', summary='Deep summary',
                                 scenario=['First call', 'Retry', 'Charged twice'],
                                 trace=[dict(line=2, step='1', note='Total computed')],
                                 root_cause='Wrong assumption', impact='Money lost',
                                 fix=dict(explanation='Add key', patch='-    gateway.send(total)\n+    gateway.send(total, key)'),
                                 test=dict(name='test_once', code='assert calls == 1'))}))
        self.assertIn('gateway.send(total)', html)              # real code, not retyped
        self.assertRegex(html, r'class="ln add[^"]*"><span class="no">3</span><span class="mk">\+')  # changed line marked
        self.assertIn('Sent without a key', html)               # pinned note
        self.assertRegex(html, r'class="ln add hit-critical"><span class="no">3<')  # pin on the requested line
        for text in ('How it breaks', 'Charged twice', 'Why it happens', 'What it costs', 'How to fix it',
                     'Prove it with a test', 'assert calls == 1', 'Total computed'):
            self.assertIn(text, html)
        self.assertIn('Charge sent twice &lt;b&gt;', html)       # finding title escaped

    def test_explainer_text_is_escaped(self):
        evil = '<script>alert(1)</script>'
        html = self.render(dict(title=evil, one_liner=evil, steps=[dict(title=evil, file='pay.py', lines=[1, 2], explanation=evil)],
                                problems={'F1': dict(scenario=[evil], root_cause=evil, fix=dict(patch='+' + evil), test=dict(code=evil))}))
        self.assertNotIn('<script>alert', html)
        self.assertIn('&lt;script&gt;', html)

    def test_old_explainer_format_still_renders(self):
        html = self.render(dict(title='Old', steps=[dict(title='S', where='pay.py:2-3', what_happens='Old text',
                                                          snippet='x', kind='logic', finding_ids=['F1'])]))
        self.assertIn('Old text', html)
        self.assertIn('gateway.send(total)', html)

    def test_missing_source_falls_back_to_diff_lines(self):
        (self.root / 'src' / 'pay.py').unlink()
        html = self.render(dict(title='Gone', steps=[dict(title='S', file='pay.py', lines=[2, 3], explanation='E')]))
        self.assertIn('gateway.send(total)', html)

    def test_thin_explanations_are_flagged(self):
        (self.pkg / 'explainer.json').write_text(json.dumps(dict(
            title='T', steps=[dict(title='S', file='pay.py', lines=[1, 2], explanation='E')],
            problems={'F1': dict(scenario=['one'], root_cause='short', test=dict(code='x' * 150))})))
        r = subprocess.run([sys.executable, str(SCRIPTS / 'render_html.py'), str(self.pkg)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        for text in ('F1: scenario has 1 steps', 'F1: root_cause is 1 words', 'F1: fix.patch missing', 'one 150-char line'):
            self.assertIn(text, r.stderr)

    def test_no_explainer_still_explains_findings(self):
        html = self.render()
        self.assertIn('Problems, in depth', html)
        self.assertIn('Use a key', html)


if __name__ == '__main__':
    unittest.main()
