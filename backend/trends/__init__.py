"""Step 6: trends, change flags and medication response, computed in code from confirmed results.

Everything here is a pure function of the confirmed observations and the medication events: nothing
is stored, so trends and flags are recomputed on every request and never go stale after an edit.
"""
