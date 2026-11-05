"""Verification gate must never mistake partial/server-only evidence for a phone."""
import copy
import unittest
from experiments.pipecat_proof.evaluation import evaluate


class PipecatEvidenceGateTests(unittest.TestCase):
    def fixture(self):
        report={'turns':[{'answer':'真实语义测试回答','pcm_bytes':6400,'errors':[],
            'speech_end_to_pcm_ms':800} for _ in range(10)],
            'streaming_passed':True,'interruption_passed':True,
            'vad_boundary_in_end_to_end_measurement':True}
        media={'small_webrtc':{'non_silent_both_directions':True}}
        turns={'complete_detected':True,'fragment_retained':True}
        browser={'semantic_playback':True,'interrupt_stops_audio':True,'physical_microphone_echo':True}
        return report,media,turns,browser

    def test_fixed_audio_or_text_only_cannot_be_called_end_to_end(self):
        report,media,turns,browser=self.fixture()
        for t in report['turns']:
            t.pop('speech_end_to_pcm_ms');t['first_pcm_ms']=8
        gate=evaluate(report,media,turns,browser)
        self.assertFalse(gate['integration_gate_passed'])
        self.assertIn('ten_real_asr_turns',gate['remaining_gates'])
        self.assertIsNone(gate['speech_end_to_server_pcm'])

    def test_server_success_does_not_replace_playback_or_physical_echo(self):
        report,media,turns,_=self.fixture()
        gate=evaluate(report,media,turns)
        self.assertTrue(gate['core_framework_passed'])
        self.assertFalse(gate['integration_gate_passed'])
        self.assertIn('browser_audio_and_interrupt',gate['remaining_gates'])
        self.assertIn('physical_microphone_echo',gate['remaining_gates'])

    def test_slow_response_error_and_missing_automatic_turns_each_block_integration(self):
        original,media,turns,browser=self.fixture()
        self.assertTrue(evaluate(original,media,turns,browser)['integration_gate_passed'])
        for change,missing in [
            (lambda r:r['turns'][0].update(speech_end_to_pcm_ms=4000),'latency_target'),
            (lambda r:r['turns'][0].update(errors=['ErrorFrame']),'ten_successful_turns'),
            (lambda r:r.update(vad_boundary_in_end_to_end_measurement=False),'automatic_turn_boundaries'),
        ]:
            report=copy.deepcopy(original);change(report)
            gate=evaluate(report,media,turns,browser)
            self.assertFalse(gate['integration_gate_passed'])
            self.assertIn(missing,gate['remaining_gates'])

if __name__=='__main__':unittest.main()
