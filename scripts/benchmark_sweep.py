"""Benchmark sweep driver — repeats x models x arms, outside pytest.

Each repeat is a full pytest invocation with a fresh LLM_TESTS_RUNS_DIR
(fresh setup models per repeat = independent trials; suite code untouched).
Copies each run's benchmark.json to results/<sweep_id>/<model>_<arm>_r<r>.json
for scripts/benchmark_aggregate.py.

Paper honesty rule: retries are forced to 0 — repeats replace them. The
sweep aborts if LLM_TESTS_RETRIES is set nonzero in the environment.

Examples (one invocation per run-matrix row; shared --sweep-id):
  python scripts/benchmark_sweep.py --sweep-id paper-v1 --image openstudio-mcp:v1.2.0 \
      --model sonnet:claude --arms full --repeats 3 --pytest-args "tests/llm"
  python scripts/benchmark_sweep.py --sweep-id paper-v1 --image openstudio-mcp:v1.2.0 \
      --model gpt-5:codex --arms full --repeats 3 --pytest-args "-m progressive tests/llm"
  python scripts/benchmark_sweep.py --sweep-id paper-v1 --image openstudio-mcp:v1.2.0 \
      --model sonnet:claude --arms noskills --repeats 3 \
      --pytest-args "-m progressive -k 'not _L3' tests/llm"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def preflight(image: str, allow_dirty: bool) -> dict:
    """Record artifact identity; abort on conditions that would taint the data."""
    if os.environ.get("LLM_TESTS_RETRIES", "0") not in ("", "0"):
        sys.exit("ABORT: LLM_TESTS_RETRIES is set nonzero — retries mask "
                 "stochasticity; repeats replace them for paper runs.")

    git = subprocess.run(
        ["git", "describe", "--tags", "--always", "--dirty"],
        capture_output=True, text=True, cwd=REPO, check=True,
    ).stdout.strip()
    if git.endswith("-dirty") and not allow_dirty:
        sys.exit(f"ABORT: working tree is dirty ({git}) — benchmark runs must "
                 "come from a committed state. Commit or pass --allow-dirty.")

    inspect = subprocess.run(
        ["docker", "image", "inspect", image,
         "--format", '{{.Id}} {{join .RepoDigests ","}}'],
        capture_output=True, text=True, check=False,
    )
    if inspect.returncode != 0:
        sys.exit(f"ABORT: docker image '{image}' not found — build it first.")
    image_id, _, repo_digests = inspect.stdout.strip().partition(" ")

    return {"git": git, "image": image, "image_id": image_id,
            "image_repo_digests": repo_digests}


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep-id", required=True)
    ap.add_argument("--model", action="append", required=True,
                    metavar="MODEL:PROVIDER",
                    help="e.g. sonnet:claude or gpt-5:codex (repeatable)")
    ap.add_argument("--arms", default="full", help="comma list: full,noskills")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--pytest-args", default="tests/llm",
                    help="args after 'pytest' (shlex-split)")
    ap.add_argument("--image", default="openstudio-mcp:dev")
    ap.add_argument("--results-root", default=str(REPO / "results"))
    ap.add_argument("--runs-root",
                    default=str(Path(tempfile.gettempdir()) / "llm-sweep"))
    ap.add_argument("--allow-dirty", action="store_true")
    args = ap.parse_args()

    meta = preflight(args.image, args.allow_dirty)
    out_dir = Path(args.results_root) / args.sweep_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sweep_meta.json").write_text(json.dumps(meta, indent=2))

    models = []
    for spec in args.model:
        model, _, provider = spec.partition(":")
        models.append((model, provider or "claude"))
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    pytest_args = shlex.split(args.pytest_args)

    failures = 0
    for model, provider in models:
        for arm in arms:
            for r in range(1, args.repeats + 1):
                tag = f"{_safe(model)}_{_safe(arm)}_r{r}"
                dest = out_dir / f"{tag}.json"
                if dest.exists():
                    print(f"[skip] {tag} — result already present")
                    continue
                runs_dir = Path(args.runs_root) / args.sweep_id / tag
                runs_dir.mkdir(parents=True, exist_ok=True)
                env = os.environ | {
                    "LLM_TESTS_ENABLED": "1",
                    "LLM_TESTS_RETRIES": "0",
                    "LLM_TESTS_MODEL": model,
                    "LLM_TESTS_PROVIDER": provider,
                    "LLM_TESTS_ARM": arm,
                    "LLM_TESTS_IMAGE": args.image,
                    "LLM_TESTS_RUNS_DIR": str(runs_dir),
                    "LLM_TESTS_RUN_META": json.dumps(meta | {"repeat": r}),
                }
                print(f"[run ] {tag}: pytest {' '.join(pytest_args)}")
                subprocess.run([sys.executable, "-m", "pytest", *pytest_args],
                               env=env, cwd=REPO, check=False)
                src = runs_dir / "benchmark.json"
                if src.exists():
                    shutil.copy2(src, dest)
                    print(f"[save] {dest}")
                else:
                    failures += 1
                    print(f"[FAIL] {tag}: no benchmark.json produced")

    print(f"Sweep done — results in {out_dir}" +
          (f" ({failures} run(s) produced no data)" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
