#!/usr/bin/env python3
"""Print the unresolved review threads of a pull request, one JSON object per line.

usage: pr_unresolved_threads.py OWNER/REPO PR_NUMBER

Two GitHub calls: the REST comment list (flat; replies point at their root through in_reply_to_id) and one GraphQL
query for the per-thread resolved flag, which REST does not expose. The grouping happens here, not in the model.
"""
import json, subprocess, sys

RESOLVED_QUERY = """
query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) { pullRequest(number: $pr) {
    reviewThreads(first: 100) { nodes { isResolved comments(first: 1) { nodes { databaseId } } } } } } }"""

def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout

def main():
    repo, pr = sys.argv[1], int(sys.argv[2])
    owner, name = repo.split("/")
    comments = [json.loads(l) for l in gh("api", f"repos/{repo}/pulls/{pr}/comments", "--paginate",
                                          "--jq", ".[] | {id, in_reply_to_id, path, line, user: .user.login, body}").splitlines()]
    threads = json.loads(gh("api", "graphql", "-f", f"query={RESOLVED_QUERY}", "-f", f"owner={owner}", "-f", f"repo={name}", "-F", f"pr={pr}"))
    resolved = {t["comments"]["nodes"][0]["databaseId"] for t in threads["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"] if t["isResolved"]}
    replies = {}
    for c in comments:
        if c["in_reply_to_id"]: replies.setdefault(c["in_reply_to_id"], []).append(c)
    for root in comments:
        if root["in_reply_to_id"] or root["id"] in resolved: continue
        thread = [root] + sorted(replies.get(root["id"], []), key=lambda c: c["id"])
        print(json.dumps({"root_comment_id": root["id"], "path": root["path"], "line": root["line"], "comments": len(thread),
                          "thread": [{"id": c["id"], "author": c["user"], "body": c["body"]} for c in thread]}))

if __name__ == "__main__": main()
