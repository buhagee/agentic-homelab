from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts/maintenance'))
import native_memory


class MemorySamples(unittest.TestCase):
    def test_global_oom_survives_cgroup_counter_reset(self):
        state = native_memory.classify('active', True, 'some avg10=0.00 avg60=0.00 avg300=0.00 total=0')
        self.assertEqual(state, {'oom': 'failed', 'pressure': 'healthy', 'service': 'healthy'})

    def test_stopped_unit_is_not_a_recovery_and_no_psi_is_unknown(self):
        self.assertEqual(native_memory.classify('inactive', False, '')['oom'], 'unknown')
        state = native_memory.classify('active', None, '')
        self.assertEqual((state['oom'], state['pressure']), ('unknown', 'unknown'))

    def test_sustained_pressure_and_service_failure_are_independent(self):
        state = native_memory.classify('active', False, 'some avg10=9.99 avg60=8.00 avg300=6.00 total=12')
        self.assertEqual(state['pressure'], 'failed')
        self.assertEqual(state['oom'], 'healthy')
        self.assertEqual(native_memory.classify('failed', False, '')['service'], 'failed')
