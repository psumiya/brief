"""
Canonical schema for brief JSON output.
Keep in sync with the OUTPUT FORMAT section in prompts.py SYSTEM_PROMPT.
"""

VALID_KICKERS = {"Lead", "Research", "Field Notes"}

VALID_THEMES = {
    "Hardware & Infrastructure",
    "Foundation Models & Research",
    "Agents & Applications",
    "Open Source & Tooling",
    "Community & Discourse",
}

VALID_STACK_LAYERS = {
    "Infrastructure / Compute",
    "Data",
    "Models / Algorithms",
    "Platforms / Tools",
    "Applications",
}

VALID_THREAD_STATUSES = {"active", "cooling", "resolved"}

FORBIDDEN_PHRASES = [
    "it remains to be seen",
    "could potentially",
    "may or may not",
    "it is worth noting",
    "it should be noted",
]

DEEP_TAKES_COUNT = 3
BULLETS_MIN = 10
BULLETS_MAX = 15
BODY_MIN_CHARS = 100
BULLET_MAX_CHARS = 300
THREAD_SUMMARY_MIN_CHARS = 50
