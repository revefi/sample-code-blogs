"""Every knob of the experiment in one place."""

# The Opus that was current in January 2026.
MODEL = "claude-opus-4-5-20251101"
# List price, $ per million tokens (cache write = 1.25x input, cache read = 0.1x input).
PRICE_PER_MTOK = {"input": 5.0, "output": 25.0, "cache_write": 6.25, "cache_read": 0.5}

# The agent is built to behave like Claude Code did in January 2026:
#  - every tool definition, including every connected MCP server's tools, sent in the system prompt on every call
#    (no progressive disclosure yet); system_prompt.txt is padded to this size
SYSTEM_PROMPT_TOKENS = 18_000
#  - a tool result over this size is written to a file; the model sees a short preview and pages through it with Read
SPILL_THRESHOLD_CHARS = 50_000
SPILL_PREVIEW_CHARS = 2_000
READ_MAX_LINES = 2_000           # Read returns at most this many lines per call
READ_MAX_LINE_CHARS = 2_000      # ...each truncated to this many characters
#  - prompt caching of the system prompt and the conversation prefix (always on)
#  - extended thinking with this budget
THINKING_BUDGET_TOKENS = 8_000
# Temperature is not set, so it is the API default of 1.0. That is also the only value the API accepts while extended
# thinking is on, and it is what Claude Code uses; expect run-to-run variation in calls and cost.

MAX_OUTPUT_TOKENS = 16_000
MAX_TURNS = 40            # LLM calls per run before giving up
BASH_TIMEOUT_S = 120
RUNS_PER_SCENARIO = 3

# The PR being replayed: an anonymized recording of a real one, 31 inline review comments in 15 threads.
REPO = "acme/widgets"
PR = 25471

# Three scenarios. The prompt for each is prompts/<scenario>.txt, appended to prompts/common.txt.
SCENARIOS = {
    "raw": "Raw JSON",              # the API response goes straight into context; no scripts, no jq
    "adhoc": "Ad-hoc script",       # same data, the model may write jq or Python on the spot
    "script": "Checked-in script",  # scripts/pr_unresolved_threads.py already does the work
}
