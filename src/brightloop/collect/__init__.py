"""The web source: capture Maya's competitor pages and turn them into signals.

The collector never decides what changed. It captures each page as a snapshot signal
(this week's, plus last week's as the baseline), writes them in the same format as the
reviewers' cases.json, and runs the same pipeline. The comparison happens in select.py.
"""
