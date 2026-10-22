# Do you know what your Claude Code is doing? Part 1

Code for the experiment in the blog post of the same name (link to follow). Short version: hand a model a raw API
response shaped for programs, such as GitHub's flat list of PR review comments, and the model rebuilds the structure in
its head on every call. A small checked-in script that does it once is a lot cheaper. This folder lets you measure that.

## What is in here

- `agent.py`: a minimal coding agent that behaves like Claude Code did in January 2026: 200K context with Opus 4.5,
  every tool definition in an 18k-token system prompt on every call (no progressive disclosure yet), tool results over
  50K characters saved to a file and paged back with `Read`, prompt caching, 8K thinking budget. All of it in `config.py`.
- `bin/gh`: a mocked GitHub CLI that replays a recorded, anonymized pull request (`fixtures/`): 31 inline comments in
  15 threads, one unresolved. REST pagination and `--jq` work; GraphQL runs on a real engine over a small GitHub
  schema; writes get a 403. Every call the model makes is logged.
- `prompts/`: the task (list the unresolved review threads) and three scenarios: **Raw JSON** (response read in
  context, no scripts), **Ad-hoc script** (model may write jq or Python), **Checked-in script**
  (`scripts/pr_unresolved_threads.py`, 35 lines, builds the threads and drops resolved ones).

## Results

Three runs per scenario, averaged. Input tokens include cache reads and writes; cost is list price with caching.
Expect minor variance when you run it yourself: the model samples at temperature 1.0 (the only value the API allows
with extended thinking on, and what Claude Code uses), so calls and cost move a little from run to run.

| Scenario | LLM calls | Tool calls | Input tokens | Cost per run | Wall clock | Correct |
|---|---:|---:|---:|---:|---:|---:|
| Raw JSON | 6.0 | 5.0 | 338,941 | $0.581 | 30 s | 3/3 |
| Ad-hoc script | 10.0 | 9.0 | 258,414 | $0.272 | 36 s | 3/3 |
| Checked-in script | 2.0 | 1.0 | 39,445 | $0.071 | 6 s | 3/3 |

## Run it

Needs Python 3.10+ and `jq`.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # paste your ANTHROPIC_API_KEY
./run.sh                      # all scenarios, 3 runs each, about $3
python3 aggregate.py          # table from runs/
```

Each run writes `runs/<scenario>-<n>/` with the prompt, every model turn and tool result (`events.jsonl`), every
GitHub call and its response size (`shim.log`), and `result.json`.

One PR, three runs per scenario: enough to see the shape of the cost, not a benchmark. The mocked `gh` does not
implement `--template`. The model's shell is a real shell on your machine, with no API key in its environment.
