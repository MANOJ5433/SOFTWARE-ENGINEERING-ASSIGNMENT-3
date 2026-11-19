"""Deterministic, explainable triage.

These are keyword rules and fixed thresholds only. No trained model, no external AI API.
Every suggestion returns the rules that produced it so a human can accept or override it.
"""
import re

SLA_HOURS = {"CRITICAL": 4, "HIGH": 24, "MEDIUM": 72, "LOW": 168}

CATEGORY_KEYWORDS = [
    ("SAFETY", ("smoke", "fire", "gas", "burning", "sparks", "hazard", "alarm")),
    ("ELECTRICAL", ("power", "electrical", "socket", "lights", "light", "wiring", "fuse", "outage")),
    ("PLUMBING", ("water", "leak", "leaking", "pipe", "drain", "tap", "toilet", "flood")),
    ("HVAC", ("air", "aircon", "hvac", "temperature", "heating", "cooling", "ventilation", "thermostat")),
    ("FURNITURE_FIXTURE", ("chair", "desk", "door", "window", "lock", "projector", "whiteboard", "table")),
]
PRIORITY_KEYWORDS = [
    ("CRITICAL", ("smoke", "fire", "gas", "burning", "sparks", "flood")),
    ("HIGH", ("leak", "leaking", "outage", "unsafe", "broken", "overheating", "lock")),
    ("LOW", ("cosmetic", "paint", "squeak", "minor", "scratch")),
]


def _first_match(text, table):
    for label, words in table:
        for word in words:
            if re.search(r"\b" + re.escape(word) + r"\b", text):
                return label, word
    return None, None


def classify(title, description=""):
    text = f"{title} {description}".lower()
    rules = []
    category, word = _first_match(text, CATEGORY_KEYWORDS)
    if category:
        rules.append(f"category={category}: keyword '{word}'")
    else:
        category = "OTHER"
        rules.append("category=OTHER: no category keyword matched")
    priority, word = _first_match(text, PRIORITY_KEYWORDS)
    if priority:
        rules.append(f"priority={priority}: keyword '{word}'")
    else:
        priority = "MEDIUM"
        rules.append("priority=MEDIUM: default, no priority keyword matched")
    return {"category": category, "priority": priority, "rules": rules}


def evaluate_sensor(sensor_type, reading, temperature_threshold, smoke_threshold):
    """Return (breached, category, priority, rules) for a controlled sensor reading."""
    if sensor_type == "SMOKE_LEVEL":
        breached = reading > smoke_threshold
        rule = f"threshold rule: SMOKE_LEVEL reading {reading} > {smoke_threshold}"
        return breached, "SAFETY", "CRITICAL", [rule]
    breached = reading > temperature_threshold
    priority = "HIGH" if reading >= temperature_threshold + 5 else "MEDIUM"
    rule = f"threshold rule: TEMPERATURE reading {reading} > {temperature_threshold}"
    return breached, "HVAC", priority, [rule]
