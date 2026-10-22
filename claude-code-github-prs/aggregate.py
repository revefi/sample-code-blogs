#!/usr/bin/env python3
"""Summarise runs/*/result.json into a table on stdout and in results.md.

A run is correct only if every field it reports matches the unresolved threads in fixtures/graphql_pr.json."""
import glob
import json
import os
import re
import statistics
import sys

import config

HERE = os.path.dirname(os.path.abspath(__file__))


def expected_threads():
    pr = json.load(open(os.path.join(HERE, "fixtures", "graphql_pr.json")))["data"]["repository"]["pullRequest"]
    expected = {}
    for thread in pr["reviewThreads"]["nodes"]:
        if thread["isResolved"]:
            continue
        comments = thread["comments"]["nodes"]
        line = thread["line"] if thread["line"] is not None else thread["originalLine"]
        expected[comments[0]["databaseId"]] = dict(path=thread["path"], line=line, comments=len(comments),
                                                    last_author=comments[-1]["author"]["login"], last_body=comments[-1]["body"].strip())
    return expected


EXPECTED = expected_threads()


def check(final_text):
    """(correct, reason) for the JSON block at the end of the model's answer."""
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", final_text or "", re.S)
    if not blocks:
        return False, "no json"
    try:
        reported = {int(t["root_comment_id"]): t for t in json.loads(blocks[-1])["unresolved_threads"]}
    except Exception as e:
        return False, f"bad json: {e}"
    if set(reported) != set(EXPECTED):
        return False, f"ids {sorted(reported)} != {sorted(EXPECTED)}"
    for root_id, want in EXPECTED.items():
        got = reported[root_id]
        wrong = [k for k in want if (str(got.get(k)).strip() if k == "last_body" else got.get(k)) != want[k]]
        if wrong:
            return False, "wrong " + ",".join(wrong)
    return True, ""


rows = []
for path in sorted(glob.glob(os.path.join(HERE, "runs", "*", "result.json"))):
    r = json.load(open(path))
    ok, reason = check(r["final"])
    rows.append(dict(scenario=r["scenario"], idx=r["idx"], status=r["status"], llm=r["llm_calls"], tools=r["tool_calls"],
                     inp=r["input_tokens_total"], out=r["usage"]["output"], cost=r["cost_usd"], wall=r["wall_s"], ok=ok, reason=reason,
                     mutations=r["mutations_attempted"]))
if not rows:
    sys.exit("no runs found; run ./run.sh first")

print(f"{'run':10} {'status':8} {'llm':>4} {'tools':>5} {'input_tok':>10} {'out_tok':>8} {'cost$':>7} {'wall':>5}  ok  note")
for r in rows:
    note = r["reason"] + (" MUTATION ATTEMPTED" if r["mutations"] else "")
    print(f"{r['scenario'] + '-' + r['idx']:10} {r['status'][:8]:8} {r['llm']:4} {r['tools']:5} {r['inp']:10,} {r['out']:8,} "
          f"{r['cost']:7.3f} {r['wall']:5.0f}  {'Y' if r['ok'] else 'N'}   {note}")

table = ["| Scenario | LLM calls | Tool calls | Input tokens | Cost per run | Wall clock | Correct |",
         "|---|---:|---:|---:|---:|---:|---:|"]
for scenario, label in config.SCENARIOS.items():
    cell = [r for r in rows if r["scenario"] == scenario]
    if not cell:
        continue
    mean = lambda key: statistics.mean(r[key] for r in cell)
    table.append(f"| {label} | {mean('llm'):.1f} | {mean('tools'):.1f} | {mean('inp'):,.0f} | ${mean('cost'):.3f} | "
                 f"{mean('wall'):.0f} s | {sum(r['ok'] for r in cell)}/{len(cell)} |")
print()
print("\n".join(table))
open(os.path.join(HERE, "results.md"), "w").write("\n".join(table) + "\n")
