"""Conservative evidence gate: fast fixed audio or text-only probes never pass."""
import math
import statistics


def distribution(values):
    if not values:
        return None
    ordered=sorted(values)
    return {'median_ms':round(statistics.median(ordered)),
            'p95_ms':ordered[math.ceil(.95*len(ordered))-1], 'samples':len(ordered)}


def evaluate(report, media=None, turns=None, browser=None):
    media=media or {};turns=turns or {};browser=browser or {}
    checks={
        'ten_successful_turns':len(report.get('turns',[]))>=10 and all(
            t.get('pcm_bytes',0)>0 and bool(t.get('answer')) and not t.get('errors') for t in report.get('turns',[])),
        'streaming_before_model_end':report.get('streaming_passed') is True,
        'server_cancellation':report.get('interruption_passed') is True,
        'webrtc_bidirectional_audio':media.get('small_webrtc',{}).get('non_silent_both_directions') is True,
        'chinese_complete_and_incomplete_turns':turns.get('complete_detected') is True and turns.get('fragment_retained') is True,
    }
    audio=[t.get('speech_end_to_pcm_ms') for t in report.get('turns',[])]
    valid=len(audio)>=10 and all(isinstance(v,(int,float)) and v>=0 for v in audio)
    times=distribution(audio) if valid else None
    checks.update({
        'ten_real_asr_turns':valid,
        'latency_target':bool(times and times['median_ms']<=1000 and times['p95_ms']<=2000),
        'automatic_turn_boundaries':report.get('vad_boundary_in_end_to_end_measurement') is True,
        'browser_audio_and_interrupt':browser.get('semantic_playback') is True and browser.get('interrupt_stops_audio') is True,
        'physical_microphone_echo':browser.get('physical_microphone_echo') is True,
    })
    core_keys=list(checks)[:5]
    return {'core_framework_passed':all(checks[k] for k in core_keys),
        'integration_gate_passed':all(checks.values()), 'checks':checks,
        'speech_end_to_server_pcm':times, 'remaining_gates':[k for k,v in checks.items() if not v]}
