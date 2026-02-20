from __future__ import annotations

import json
import time
from pathlib import Path

from mcp_server.skills.results.operations import extract_summary_metrics
from mcp_server.skills.simulation.operations import get_run_status, run_osw

FIX = Path("tests/fixtures")
OSW = FIX / "workflow.osw"
EPW = FIX / "weather.epw"


def main():
    if not OSW.exists():
        raise SystemExit("Missing tests/fixtures/workflow.osw")
    epw = str(EPW) if EPW.exists() else None

    resp = run_osw(str(OSW), epw_path=epw, name="generate-golden")
    if not resp.get("ok"):
        raise SystemExit(resp)
    run_id = resp["run_id"]

    deadline = time.time() + 60 * 30
    while time.time() < deadline:
        s = get_run_status(run_id)
        st = s["run"]["status"]
        if st in ("success", "failed", "canceled"):
            break
        time.sleep(2)
    if st != "success":
        raise SystemExit(f"Run did not succeed: {st}")

    met = extract_summary_metrics(run_id)
    if not met.get("ok"):
        raise SystemExit(met)

    out = {
        "unmet_hours_heating": met["metrics"]["unmet_hours_heating"],
        "unmet_hours_cooling": met["metrics"]["unmet_hours_cooling"],
        "eui": met["metrics"]["eui"],
        "eui_units": met["metrics"]["eui_units"],
    }
    out_path = FIX / "golden" / "metrics.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
