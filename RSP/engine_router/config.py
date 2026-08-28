#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — engine_router/config.py

فقط همان یک سوئیچی که قرار بود باشد. هیچ پارامتر استراتژیک اینجا نیست.
"""

import os

# "legacy" | "rsp" | "shadow"  — پیش‌فرض shadow طبق دستور صریح.
ENGINE_MODE = os.environ.get("ARSAN_ENGINE_MODE", "shadow")

VALID_MODES = ("legacy", "rsp", "shadow")
