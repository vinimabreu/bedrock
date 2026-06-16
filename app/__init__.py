"""Bedrock: a natural-language-to-SQL data agent with a stability harness.

The agent answers a database in plain English with safe, read-only, cited SQL.
The flagship layer runs every business-critical question K times and scores it
against a defended answer key: not just "is it right" but "is it right the SAME
way every time", so a question that is right 3 runs of 5 is flagged as FLAKY
instead of being shipped on a lucky single run.
"""
