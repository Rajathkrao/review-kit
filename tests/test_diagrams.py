"""Diagrams are drawn by the renderer from boxes and arrows, escaped, and linked to findings."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/review-kit/scripts'))
import diagrams
from test_html import SCRIPTS, Walkthrough as _Base


class DiagramUnits(unittest.TestCase):
    def test_architecture_layers_and_badges(self):
        svg = diagrams.architecture({'nodes': [
            {'id': 'api', 'label': 'POST /pay <x>', 'kind': 'request', 'changed': True, 'finding_ids': ['F1']},
            {'id': 'svc', 'label': 'PaymentService.charge_customer_now', 'file': 'pay/service.py'},
            {'id': 'gw', 'label': 'Gateway', 'kind': 'external'}],
            'edges': [{'from': 'api', 'to': 'svc', 'label': 'charge'}, {'from': 'svc', 'to': 'gw'},
                      {'from': 'gw', 'to': 'api', 'label': 'webhook'}, {'from': 'svc', 'to': 'missing'}]},
            {'F1': {'severity': 'critical'}})
        self.assertTrue(svg.startswith('<svg'))
        self.assertIn('POST /pay &lt;x&gt;', svg)
        self.assertIn('href="#F1"', svg)
        self.assertIn('dg-changed', svg)
        self.assertIn('dg-external', svg)
        self.assertEqual(svg.count('class="dg-edge"'), 3)  # edge to an unknown node is dropped
        self.assertNotIn('PaymentService.charge_customer_now<', svg)  # long names wrap

    def test_empty_specs_draw_nothing(self):
        self.assertEqual(diagrams.architecture({}), '')
        self.assertEqual(diagrams.sequence({'actors': ['A']}), '')

    def test_sequence_marks_the_failing_message(self):
        svg = diagrams.sequence({'actors': ['Bank', 'Svc'], 'messages': [
            {'from': 'Bank', 'to': 'Svc', 'label': 'event e1'},
            {'from': 'Bank', 'to': 'Svc', 'label': 'retry e1', 'finding_id': 'F2'},
            {'from': 'Svc', 'to': 'Svc', 'label': 'two rows', 'kind': 'note'}]}, {'F2': {'severity': 'important'}})
        self.assertIn('retry e1', svg)
        self.assertIn('href="#F2"', svg)
        self.assertIn('var(--imp)', svg)

    def test_long_sequence_labels_wrap_and_keep_full_text(self):
        long = 'event_id=e1, merchant_id=m1, amount_cents=1000, installments=4'
        svg = diagrams.sequence({'actors': ['Bank', 'Svc'], 'messages': [{'from': 'Bank', 'to': 'Svc', 'label': long}]})
        self.assertIn(f'<title>{long}</title>', svg)
        self.assertGreaterEqual(svg.count('class="dg-label"'), 2)

    def test_import_graph_from_source(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'app').mkdir()
            (root / 'app/__init__.py').write_text('')
            (root / 'app/store.py').write_text('X = 1\n')
            (root / 'app/service.py').write_text('from .store import X\nimport json\n')
            (root / 'app/api.py').write_text('from app.service import X\n')
            g = diagrams.import_graph(root, ['app/service.py'])
            ids = {n['id'] for n in g['nodes']}
            self.assertEqual(ids, {'app.service', 'app.store', 'app.api'})
            self.assertIn({'from': 'app.service', 'to': 'app.store'}, g['edges'])
            self.assertIn({'from': 'app.api', 'to': 'app.service'}, g['edges'])
            self.assertTrue(next(n for n in g['nodes'] if n['id'] == 'app.service')['changed'])


class PageSections(_Base):
    def test_big_picture_worth_a_look_and_reading_order(self):
        fx = json.loads((self.pkg / 'findings.json').read_text())
        fx['plausible'] = [{'title': 'Naive datetime', 'file': 'pay.py', 'line_start': 2, 'check': 'are rows aware?'}]
        fx['dropped'] = [{'title': 'N+1', 'reason': 'guard at pay.py:1'}]
        (self.pkg / 'findings.json').write_text(json.dumps(fx))
        html = self.render(dict(title='Payments',
            architecture={'nodes': [{'id': 'a', 'label': 'charge', 'changed': True, 'finding_ids': ['F1']},
                                    {'id': 'b', 'label': 'gateway', 'kind': 'external'}], 'edges': [{'from': 'a', 'to': 'b'}]},
            sequences=[{'title': 'Retry', 'actors': ['A', 'B'], 'messages': [{'from': 'A', 'to': 'B', 'label': 'send'}]}],
            changed_files=[{'path': 'pay.py', 'role': 'Read first', 'order': 1}]))
        for text in ('The big picture', '<svg class="dg"', 'Retry', 'Worth a look', 'are rows aware?',
                     'Dismissed', 'guard at pay.py:1', 'Suggested reading order', 'Review effort'):
            self.assertIn(text, html)

    def test_problem_files_from_parallel_writers_are_merged(self):
        (self.pkg / 'problems-1.json').write_text(json.dumps({'F1': dict(
            pin_line=3, summary='Written by a parallel writer', root_cause='Wrong assumption')}))
        html = self.render(dict(title='Payments'))
        self.assertIn('Written by a parallel writer', html)

    def test_ids_from_before_verification_are_renumbered(self):
        fx = json.loads((self.pkg / 'findings.json').read_text())
        fx['findings'][0]['id'] = 'F4'
        (self.pkg / 'findings.json').write_text(json.dumps(fx))
        (self.pkg / 'problems-2.json').write_text(json.dumps({'F4': dict(pin_line=3, summary='Kept with its finding')}))
        html = self.render(dict(title='Payments', steps=[dict(title='Charge', file='pay.py', lines=[1, 4],
                                                               explanation='Explains', finding_ids=['F4'])]))
        self.assertIn('Kept with its finding', html)
        self.assertIn('href="#F1"', html)
        self.assertNotIn('F4', html)

    def test_glance_table_fix_prompts_and_folding(self):
        html = self.render(dict(title='Payments', problems={'F1': dict(
            summary='Deep summary', scenario=['First call', 'Retry'],
            fix=dict(explanation='Send an idempotency key.'), test=dict(code='assert calls == 1', explanation='Fails today.'))}))
        for text in ('Problems at a glance', 'data-filter="critical"', 'Copy all fix prompts', 'Copy fix prompt',
                     'Fix this code review finding.', 'Where: pay.py:1-4', 'How it breaks: 1) First call 2) Retry',
                     '<details class="fold">', 'id="fold-all"'):
            self.assertIn(text, html)

    def test_copy_to_writes_a_copy_and_prints_a_file_link(self):
        (self.pkg / 'explainer.json').write_text(json.dumps(dict(title='Payments')))
        r = subprocess.run([sys.executable, str(SCRIPTS / 'render_html.py'), str(self.pkg), '--copy-to', str(self.root / 'out')],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        copy = self.root / 'out' / 'pkg.html'
        self.assertTrue(copy.is_file())
        self.assertEqual(r.stdout.splitlines()[-2:], [str(copy), copy.resolve().as_uri()])

    def test_explain_mode_has_no_verdict(self):
        (self.pkg / 'findings.json').write_text(json.dumps(dict(
            mode='explain', execution_status='completed', verdict='ship', summary='Explained pay.py', findings=[])))
        html = self.render(dict(title='Payments'))
        self.assertIn('Walkthrough only, not reviewed for bugs', html)
        self.assertNotIn('No issues found', html)


del _Base

if __name__ == '__main__':
    unittest.main()
