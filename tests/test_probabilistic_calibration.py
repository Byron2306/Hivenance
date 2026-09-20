from strategies.relative_value_lab.probabilistic_calibration import (
    OnlineConformalCalibrator,
    RollingCalibrationMonitor,
    StochasticVolatilityFilter,
    probability_ratios,
)


def test_probability_ratios_are_explicit_and_non_authoritative():
    state=probability_ratios(
        as_of_ms=100,
        edge_positive_probability=.75,
        trend_probability=.6,
        mean_reversion_probability=.3,
        long_liquidation_probability=.2,
        short_liquidation_probability=.4,
        support_weight=3,
        dissent_weight=1,
        implied_volatility=.8,
        realized_volatility=.4,
        open_interest=200,
        spot_volume=100,
    )
    assert state.posterior_odds==3.0
    assert state.trend_mean_reversion_odds==2.0
    assert state.liquidation_asymmetry==.5
    assert state.model_support_dissent_ratio==3.0
    assert state.iv_realized_vol_ratio==2.0
    assert state.oi_spot_volume_ratio==2.0
    assert state.execution_eligible is False


def test_stochastic_volatility_filter_reacts_to_shock():
    f=StochasticVolatilityFilter()
    calm=None
    for i in range(20):
        calm=f.update(return_value=.001,as_of_ms=i+1)
    shock=f.update(return_value=.08,as_of_ms=30)
    assert shock.expected_volatility>calm.expected_volatility
    assert shock.expansion_probability>calm.expansion_probability
    assert 0.0<=shock.stress_probability<=1.0


def test_online_conformal_interval_and_coverage_state():
    c=OnlineConformalCalibrator(window=50)
    for i in range(20):
        prediction=float(i)
        realized=float(i)+(.5 if i%2==0 else -.5)
        prior=(prediction-1.0,prediction+1.0)
        c.observe(prediction=prediction,realized=realized,prior_interval=prior)
    interval=c.interval(prediction=100.0,as_of_ms=1000,target_coverage=.8)
    assert interval.lower<100.0<interval.upper
    assert interval.empirical_coverage==1.0
    assert interval.calibration_state=="UNDERCONFIDENT"
    assert interval.execution_eligible is False


def test_rolling_calibration_monitor_tracks_brier_logloss_and_drift():
    m=RollingCalibrationMonitor(window=40)
    for i in range(20):
        m.observe(
            probability=.8 if i<10 else .2,
            label=(i<10),
            residual=.2 if i<10 else 2.0,
            feature_score=0.1 if i<10 else 1.0,
        )
    h=m.health()
    assert h.sample_count==20
    assert h.brier_score is not None
    assert h.log_loss is not None
    assert h.calibration_error is not None
    assert h.feature_drift_score>0
    assert h.residual_drift_score>0
    assert h.overall_drift_score>0
    assert h.execution_eligible is False
