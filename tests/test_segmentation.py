import numpy as np
import pytest

from acustica_materiales.segmentation import detect_candidates


def test_two_impacts_keep_tails_separate_and_weak_event():
    fs = 10000
    rng = np.random.default_rng(42)
    x = rng.normal(0, .0003, 30000)
    for start, amplitude in [(5000, .5), (18000, .08)]:
        t = np.arange(5000) / fs
        x[start:start+5000] += amplitude * np.exp(-t/.04) * np.sin(2*np.pi*700*t)
    rows, _ = detect_candidates(x, fs)
    assert len(rows) == 2
    for row, onset in zip(rows, [5000, 18000]):
        assert row['inicio_muestra'] < onset < row['fin_muestra']
        assert row['fin_muestra'] > onset + 1000
    assert rows[0]['fin_muestra'] <= rows[1]['inicio_muestra']


def test_silence_has_no_candidates_and_stereo_requires_explicit_choice():
    rows, _ = detect_candidates(np.zeros(10000), 10000)
    assert rows == []
    with pytest.raises(ValueError):
        detect_candidates(np.zeros((10000, 2)), 10000)


def test_long_tail_stops_before_next_event_and_marks_limit():
    fs = 10000
    x = np.zeros(30000)
    t = np.arange(20000) / fs
    x[10000:] = .5*np.exp(-t/2)*np.sin(2*np.pi*700*t)
    x[23000:23050] += .8
    rows, _ = detect_candidates(x, fs)
    assert all(0 <= r['inicio_muestra'] < r['fin_muestra'] <= len(x) for r in rows)
    assert all(a['fin_muestra'] <= b['inicio_muestra'] for a, b in zip(rows, rows[1:]))
    assert any('Cola limitada' in warning for r in rows for warning in r['avisos'])
