#!/usr/bin/env python3
"""A minimal tool-use agent that behaves like Claude Code did in January 2026, run against a mocked GitHub.

usage: agent.py --scenario raw|adhoc|script --idx N
Needs ANTHROPIC_API_KEY in the environment (run.sh loads it from .env).
Writes runs/<scenario>-<idx>/: prompt.txt, events.jsonl (every turn, tool call and tool result),
shim.log (every GitHub call the model made) and result.json.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

import anthropic

import config

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT = open(os.path.join(HERE, "system_prompt.txt")).read()

BASH_TOOL = {
    "name": "Bash",
    "description": "Run a shell command in the working directory and return its output.",
    "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
}
READ_TOOL = {
    "name": "Read",
    "description": (f"Read a slice of a file. Returns up to {config.READ_MAX_LINES} lines in `cat -n` format; lines longer "
                    f"than {config.READ_MAX_LINE_CHARS} characters are truncated. Use offset and limit to page through large files."),
    "input_schema": {"type": "object", "properties": {
        "file_path": {"type": "string"},
        "offset": {"type": "integer", "description": "1-based line to start from (default 1)"},
        "limit": {"type": "integer", "description": f"number of lines (default {config.READ_MAX_LINES})"},
    }, "required": ["file_path"]},
}
# The raw scenario may only run plain `gh api ...`: no pipes, filters, scripts or redirects.
RAW_FLOW_DENY = re.compile(r"\||\b(jq|python3?|awk|sed|grep|perl|node|ruby|xargs|tee|head|tail|cut|sort|uniq|wc|cat)\b|>\s*\S|<<|\$\(|`")
# Anything that would change the PR. The mocked gh refuses these anyway; we count the attempts.
MUTATION = re.compile(r"-X\s*(POST|PATCH|PUT|DELETE)|--method[= ]\s*(POST|PATCH|PUT|DELETE)|resolveReviewThread|addPullRequestReview|-f\s*body=|gh pr (comment|review|edit|close|merge)|\bmutation\b")


def run_bash(command, cwd, env):
    try:
        proc = subprocess.run(["bash", "-c", command], cwd=cwd, env=env, capture_output=True, text=True, timeout=config.BASH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"[command timed out after {config.BASH_TIMEOUT_S}s]"
    out = proc.stdout
    if proc.stderr:
        out += ("\n" if out and not out.endswith("\n") else "") + proc.stderr
    if proc.returncode != 0:
        out += f"\n[exit code {proc.returncode}]"
    return out if out.strip() else "(no output)"


def read_file(path, offset, limit, cwd):
    full = path if os.path.isabs(path) else os.path.join(cwd, path)
    if not os.path.isfile(full):
        return f"File does not exist: {path}"
    lines = open(full, errors="replace").read().split("\n")
    offset = max(1, offset or 1)
    limit = min(limit or config.READ_MAX_LINES, config.READ_MAX_LINES)
    selected = lines[offset - 1:offset - 1 + limit]
    out = "\n".join(f"{offset + i:6}\t{line[:config.READ_MAX_LINE_CHARS]}" for i, line in enumerate(selected))
    last = offset + len(selected) - 1
    if last < len(lines):
        out += f"\n\n(showing lines {offset}-{last} of {len(lines)}; use offset={last + 1} to continue)"
    return out or "(empty)"


def spill_to_file(output, work_dir, call_number):
    """Claude Code's behaviour for big tool outputs: save to disk, show a preview and the path."""
    out_dir = os.path.join(work_dir, ".tool-outputs")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"output-{call_number}.txt")
    open(path, "w").write(output)
    n_lines = output.count("\n") + 1
    return (f"Output too large to display ({len(output):,} characters, {n_lines:,} lines). Full output saved to: {path}\n"
            f"Use the Read tool with offset/limit to read it in parts.\n\n"
            f"Preview (first {config.SPILL_PREVIEW_CHARS:,} characters):\n{output[:config.SPILL_PREVIEW_CHARS]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True, choices=config.SCENARIOS)
    parser.add_argument("--idx", required=True)
    args = parser.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set (run.sh loads it from .env; for a single run: set -a; . .env; set +a)")

    run_dir = os.path.join(HERE, "runs", f"{args.scenario}-{args.idx}")
    shutil.rmtree(run_dir, ignore_errors=True)
    work_dir = os.path.join(run_dir, "work")
    os.makedirs(work_dir)
    if args.scenario == "script":
        os.makedirs(os.path.join(work_dir, "scripts"))
        shutil.copy(os.path.join(HERE, "scripts", "pr_unresolved_threads.py"), os.path.join(work_dir, "scripts"))

    # The run id makes each prompt unique, so a later run cannot get cache hits on an earlier run's conversation.
    prompt = (open(os.path.join(HERE, "prompts", "common.txt")).read().strip() + "\n\n"
              + open(os.path.join(HERE, "prompts", f"{args.scenario}.txt")).read().strip()
              + f"\n\nRun id: {uuid.uuid4().hex[:8]}")
    open(os.path.join(run_dir, "prompt.txt"), "w").write(prompt)

    # The model's shell sees the mocked gh first and the same python as this process, and has no API key.
    shell_env = dict(os.environ,
                     PATH=os.path.join(HERE, "bin") + ":" + os.path.dirname(sys.executable) + ":" + os.environ["PATH"],
                     GH_SHIM_LOG=os.path.join(run_dir, "shim.log"),
                     GH_FIXTURES=os.path.join(HERE, "fixtures"))
    del shell_env["ANTHROPIC_API_KEY"]

    client = anthropic.Anthropic()
    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    tools = [BASH_TOOL, READ_TOOL]
    messages = [{"role": "user", "content": prompt}]

    events = open(os.path.join(run_dir, "events.jsonl"), "w")
    def log(kind, **fields):
        events.write(json.dumps(dict(t=time.time(), type=kind, **fields)) + "\n")
        events.flush()
    log("start", scenario=args.scenario, model=config.MODEL, prompt=prompt)

    usage = dict(input=0, output=0, cache_read=0, cache_write=0)
    calls = []
    turns = 0
    final_text = ""
    status = "ok"
    mutations = 0
    started = time.time()

    while turns < config.MAX_TURNS:
        turns += 1
        try:
            response = client.messages.create(
                model=config.MODEL, max_tokens=config.MAX_OUTPUT_TOKENS, system=system, tools=tools, messages=messages,
                thinking={"type": "enabled", "budget_tokens": config.THINKING_BUDGET_TOKENS})
        except anthropic.APIError as e:
            status = "context_overflow" if "prompt is too long" in str(e) else f"api_error: {e}"
            log("error", error=str(e))
            break
        usage["input"] += response.usage.input_tokens
        usage["output"] += response.usage.output_tokens
        usage["cache_read"] += response.usage.cache_read_input_tokens or 0
        usage["cache_write"] += response.usage.cache_creation_input_tokens or 0
        content = [block.model_dump() for block in response.content]
        log("assistant", turn=turns, stop=response.stop_reason, usage=response.usage.model_dump(), content=content)
        messages.append({"role": "assistant", "content": content})

        tool_uses = [block for block in response.content if block.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            final_text = "".join(block.text for block in response.content if block.type == "text")
            break

        results = []
        for use in tool_uses:
            if use.name == "Read":
                description = f"Read {use.input.get('file_path')} offset={use.input.get('offset')} limit={use.input.get('limit')}"
                output = read_file(use.input.get("file_path", ""), use.input.get("offset"), use.input.get("limit"), work_dir)
            elif use.name != "Bash":
                description = f"{use.name} {json.dumps(use.input)[:200]}"
                output = f"Unknown tool: {use.name}. Available tools: " + ", ".join(t["name"] for t in tools)
            else:
                command = use.input.get("command", "")
                description = command
                if MUTATION.search(command):
                    mutations += 1
                if args.scenario == "raw" and (not command.strip().startswith("gh api") or RAW_FLOW_DENY.search(command)):
                    output = "Permission denied: in this run only plain `gh api ...` commands are allowed (no pipes, jq, python, scripts or redirects)."
                else:
                    output = run_bash(command, work_dir, shell_env)
                    if len(output) > config.SPILL_THRESHOLD_CHARS:
                        output = spill_to_file(output, work_dir, len(calls) + 1)
            calls.append(dict(turn=turns, tool=use.name, command=description, result_bytes=len(output)))
            log("tool", turn=turns, tool=use.name, command=description, result_bytes=len(output), result=output)
            results.append({"type": "tool_result", "tool_use_id": use.id, "content": output})

        # Cache everything up to and including the newest tool result; only the latest marker counts.
        for message in messages:
            if message["role"] == "user" and isinstance(message["content"], list):
                for block in message["content"]:
                    block.pop("cache_control", None)
        results[-1]["cache_control"] = {"type": "ephemeral"}
        messages.append({"role": "user", "content": results})
    else:
        status = "max_turns"

    price = config.PRICE_PER_MTOK
    cost = (usage["input"] * price["input"] + usage["output"] * price["output"]
            + usage["cache_read"] * price["cache_read"] + usage["cache_write"] * price["cache_write"]) / 1e6
    result = dict(scenario=args.scenario, idx=args.idx, model=config.MODEL, status=status,
                  llm_calls=turns, tool_calls=len(calls), usage=usage,
                  input_tokens_total=usage["input"] + usage["cache_read"] + usage["cache_write"],
                  cost_usd=round(cost, 4), wall_s=round(time.time() - started, 1),
                  mutations_attempted=mutations, final=final_text, calls=calls)
    json.dump(result, open(os.path.join(run_dir, "result.json"), "w"), indent=1)
    log("result", **{k: v for k, v in result.items() if k != "calls"})
    print(json.dumps({k: result[k] for k in ("scenario", "idx", "status", "llm_calls", "tool_calls", "input_tokens_total", "cost_usd", "wall_s")}))


if __name__ == "__main__":
    main()
