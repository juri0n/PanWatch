"""Prepare an upstream merge object without checking out, changing refs or pushing."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess


def git(repo, *args, check=True, env=None):
    return subprocess.run(["git", "-C", str(repo), *args], check=check, env=env,
                          text=True, encoding="utf-8", capture_output=True)


def revision(repo, ref):
    return git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").stdout.strip()


def prepare_candidate(repo, base, upstream):
    base, upstream = revision(repo, base), revision(repo, upstream)
    result = {"base_sha": base, "upstream_sha": upstream, "candidate_sha": None,
              "changed": False, "conflict_paths": []}
    ancestor = git(repo, "merge-base", "--is-ancestor", upstream, base, check=False)
    if ancestor.returncode == 0:
        return {**result, "status": "unchanged", "candidate_sha": base}
    if ancestor.returncode != 1:
        raise RuntimeError("cannot determine upstream ancestry")
    tree = git(repo, "merge-tree", "--write-tree", "--name-only", "--no-messages",
               base, upstream, check=False)
    if tree.returncode == 1:
        return {**result, "status": "conflict",
                "conflict_paths": [line for line in tree.stdout.splitlines()[1:] if line]}
    if tree.returncode:
        raise RuntimeError("merge-tree failed; no candidate published")
    tree_sha = tree.stdout.splitlines()[0]
    stamp = max(int(git(repo, "show", "-s", "--format=%ct", sha).stdout.strip())
                for sha in [base, upstream]) + 1
    env = {**os.environ, "GIT_AUTHOR_NAME": "PanWatch upstream sync",
           "GIT_AUTHOR_EMAIL": "sync@localhost", "GIT_COMMITTER_NAME": "PanWatch upstream sync",
           "GIT_COMMITTER_EMAIL": "sync@localhost", "GIT_AUTHOR_DATE": f"{stamp} +0000",
           "GIT_COMMITTER_DATE": f"{stamp} +0000"}
    candidate = git(repo, "commit-tree", tree_sha, "-p", base, "-p", upstream,
                    "-m", f"chore: sync PanWatch upstream {upstream}", env=env).stdout.strip()
    return {**result, "status": "ready", "changed": True, "candidate_sha": candidate}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--github-output")
    args = parser.parse_args()
    result = prepare_candidate(args.repo, args.base, args.upstream)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as stream:
            stream.write(f"sha={result['candidate_sha'] or ''}\nchanged={str(result['changed']).lower()}\n")
    return 2 if result["status"] == "conflict" else 0


if __name__ == "__main__":
    raise SystemExit(main())
