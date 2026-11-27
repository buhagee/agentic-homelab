import concurrent.futures
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts/lib'))
import incident


class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.db = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'state.sqlite'
        self.mail = []

    def sample(self, key, status, t, deliver=None):
        incident.observe(self.db, key, status, 'diagnostic', deliver or self.mail.append, now=t)

    def test_concurrent_reports_one_failure_independent_recovery_and_recurrence(self):
        with concurrent.futures.ThreadPoolExecutor(4) as workers:
            list(workers.map(lambda i: self.sample('oom', 'failed', 100+i), range(8)))
        self.sample('proxy', 'failed', 120)
        for status, t in [('healthy', 121), ('failed', 140), ('healthy', 160),
                          ('healthy', 161), ('unknown', 180), ('healthy', 260),
                          ('healthy', 400), ('failed', 500)]:
            self.sample('oom', status, t)
        self.assertEqual([m[0] for m in self.mail], [
            'Qacey oom failed', 'Qacey proxy failed', 'Qacey oom recovered', 'Qacey oom failed'])

    def test_delivery_failure_retried_even_after_recovery(self):
        def unavailable(message):
            raise OSError('mail unavailable')
        for status, t in [('failed', 100), ('healthy', 200), ('healthy', 400)]:
            with self.assertRaises(OSError):
                self.sample('deploy', status, t, unavailable)
        self.sample('deploy', 'healthy', 500)
        self.assertEqual([m[0] for m in self.mail], ['Qacey deploy failed', 'Qacey deploy recovered'])
