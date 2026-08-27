"""
RSP — Live-data / paper-trading validation phase.

This package does NOT tune, optimize, or retrain anything. It loads the
already-locked baseline parameters from a calibration report (produced by
RSP.calibration.run_calibration) and applies them UNCHANGED to run the
real decision pipeline against live, real-time market data. No synthetic
data. No real capital or exchange execution — every "trade" is a paper
position tracked in a local JSONL ledger until it hits its TP/SL/timeout.

Modules:
  locked_config.py   — loads + applies the frozen baseline params (read-only)
  ledger.py           — append-only decision log + open/closed paper positions
  runner.py           — one validation cycle: fetch live data, decide, log,
                         update open positions
  evaluate.py          — statistics report (win rate, net return, PF,
                         expectancy, max DD, trade count, regime breakdown),
                         gated behind a minimum sample size
"""
