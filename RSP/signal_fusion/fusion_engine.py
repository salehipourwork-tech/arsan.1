#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP Fusion Engine v2.0
وزن‌دهی پویا بر اساس رژیم + حذف اندیکاتورهای مرده
"""

from RSP.regime_switch.regime_switch import get_regime_weights, REGIME_BASE_CONFIDENCE


def compute_fusion_score(confluence_result, volume_conf=1.0, momentum_score=0.0):
    """
    confluence_result: خروجی generate_confluence()
    خروجی: dict با fusion_score, final_direction, meta
    """
    regime = confluence_result["regime"]
    filtered = confluence_result["filtered_signals"]
    direction = confluence_result["direction"]
    agreement_ratio = confluence_result["agreement_ratio"]
    
    if not direction or not filtered:
        return {
            "final_direction": None,
            "fusion_score": 0.0,
            "meta": {"reason": "No confluence or blocked"}
        }
    
    # ── وزن‌های پویا بر اساس رژیم ──
    dynamic_weights = get_regime_weights(regime)
    
    # اگر اندیکاتوری در filtered هست ولی در dynamic_weights نیست، وزن صفر
    scored = {}
    for ind, sig in filtered.items():
        w = dynamic_weights.get(ind, 0.0)
        val = 1.0 if sig == "BUY" else -1.0
        scored[ind] = val * w
    
    weighted_sum = sum(scored.values())
    
    # ── اعمال confidence رژیم + حجم + مومنتوم ──
    base_conf = REGIME_BASE_CONFIDENCE.get(regime, 0.5)
    volume_confidence = min(max(volume_conf, 0.3), 1.0)  # کلیپ ۰.۳-۱.۰
    
    # مومنتوم فقط در روند قوی تأثیرگذار است
    momentum_boost = 0.0
    if "UPTREND" in regime and momentum_score > 0:
        momentum_boost = momentum_score * 0.15
    elif "DOWNTREND" in regime and momentum_score < 0:
        momentum_boost = abs(momentum_score) * 0.15
    
    final_score = weighted_sum * base_conf * volume_confidence
    final_score += momentum_boost if direction == "BUY" else -momentum_boost
    final_score = round(final_score, 4)
    
    # ── آستانه‌های ورود ──
    THRESHOLD_BUY = 0.35
    THRESHOLD_SELL = -0.35
    
    if final_score >= THRESHOLD_BUY:
        final_direction = "BUY"
    elif final_score <= THRESHOLD_SELL:
        final_direction = "SELL"
    else:
        final_direction = None
    
    return {
        "final_direction": final_direction,
        "fusion_score": final_score,
        "meta": {
            "regime": regime,
            "dynamic_weights": dynamic_weights,
            "scored": scored,
            "base_confidence": base_conf,
            "volume_confidence": volume_confidence,
            "momentum_boost": round(momentum_boost, 4),
            "threshold_used": THRESHOLD_BUY if direction == "BUY" else abs(THRESHOLD_SELL),
        }
    }
