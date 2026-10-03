"""The model gate's threshold logic (pure; the scoring needs local images)."""
from __future__ import annotations

import pytest

from pipeline.cv_waqf import gate


def _result(q_exact=0.965, q_wrong=4, q_prec=0.98, b_exact=0.93):
    return {
        'qatar': {
            'positive_exact_accuracy': q_exact, 'wrong_symbol': q_wrong,
            'precision': q_prec,
        },
        'bahrain': {'positive_exact_accuracy': b_exact},
    }


def test_the_shipped_numbers_pass_with_room_to_spare():
    # The three measured CNN seeds, worst value of each metric.
    worst = _result(q_exact=0.957, q_wrong=4, q_prec=0.977, b_exact=0.920)
    assert gate.violations(gate.mean_metrics([worst])) == []


def test_a_real_regression_trips_the_gate_per_metric():
    cases = {
        'qatar positive_exact_accuracy': _result(q_exact=0.90),
        'qatar wrong_symbol': _result(q_wrong=14),
        'qatar precision': _result(q_prec=0.93),
        'bahrain positive_exact_accuracy': _result(b_exact=0.85),
    }
    for expected, result in cases.items():
        failures = gate.violations(gate.mean_metrics([result]))
        assert len(failures) == 1 and failures[0].startswith(expected)


def test_a_candidate_is_judged_on_the_mean_of_its_seeds_not_one_run():
    # One unlucky seed below the Qatar floor, but the candidate's mean is fine.
    seeds = [_result(q_exact=0.925), _result(q_exact=0.970), _result(q_exact=0.965)]
    means = gate.mean_metrics(seeds)
    assert means['qatar']['positive_exact_accuracy'] == pytest.approx(0.9533, abs=1e-3)
    assert gate.violations(means) == []
    # ...and one lucky seed cannot rescue a candidate that is bad on average.
    seeds = [_result(q_exact=0.985), _result(q_exact=0.88), _result(q_exact=0.89)]
    assert gate.violations(gate.mean_metrics(seeds))


def test_limits_are_inclusive_at_the_boundary():
    edge = _result(q_exact=0.930, q_wrong=8, q_prec=0.960, b_exact=0.890)
    assert gate.violations(gate.mean_metrics([edge])) == []


def test_mean_metrics_rejects_an_empty_candidate():
    with pytest.raises(ValueError, match='no results'):
        gate.mean_metrics([])


def test_floors_sit_below_the_measured_range_but_are_not_vacuous():
    q = gate.FLOORS['qatar']
    assert q['positive_exact_accuracy'][1] < 0.957 < 1.0       # below worst seed
    assert q['positive_exact_accuracy'][1] > 0.90               # still meaningful
    assert q['wrong_symbol'][1] < 14                           # MLP-seed levels fail
    assert gate.FLOORS['bahrain']['positive_exact_accuracy'][1] < 0.920
