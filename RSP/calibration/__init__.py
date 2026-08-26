"""
RSP.calibration — Walk-Forward Calibration & Robustness system for Arsan/RSP.

Ties together (without duplicating) the existing modules:
  - RSP.walk_forward            (windowing)
  - RSP.anti_overfitting        (IS/OOS degradation check)
  - RSP.robustness               (monte carlo, stress test)
  - RSP.meta_controller / fuzzy_core / risk_engine   (the 4 modes + risk knobs)

and adds what was missing for the mission in the brief:
  - a full tunable-parameter registry across Baseline/Fuzzy/AHP/Meta + risk
  - a real Train/IS -> Calibration -> LOCK -> Gap/Purge -> OOS -> Final
    Holdout protocol (the shipped walk_forward.py only windows and never
    locks/searches parameters; final holdout did not exist anywhere)
  - a golden-rule accept/reject gate (IS up & OOS down => reject, always)
  - one-protocol comparison of the four modes + ablation attribution
  - ±5% / ±10% parameter-perturbation sensitivity analysis around whatever
    was actually locked (the shipped perturbation suite only used a fixed,
    hand-picked scenario list, not the live locked parameter set)

Entry point: RSP/calibration/run_calibration.py
"""
