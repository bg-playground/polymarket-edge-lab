#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from polymarket_edge_lab.config.targets import load_targets


def _infer_timestamp_unit(value: object) -> str:
    try:
        raw = int(str(value))
    except ValueError:
        return "unknown"
    return "milliseconds" if raw >= 100_000_000_000 else "seconds"


def _query(client: httpx.Client, *, account: str, params: dict[str, str | int]) -> tuple[int, str]:
    resp = client.get("https://data-api.polymarket.com/trades", params={"user": account, **params})
    return resp.status_code, resp.text


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate live Polymarket Data API behavior")
    parser.add_argument("--account", default=None, help="Public proxy wallet address")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/LIVE_API_VALIDATION.md"),
        help="Markdown output path",
    )
    args = parser.parse_args()

    targets = load_targets(Path("config/targets.json"))
    cfg = targets.get("nagi777")
    account = args.account or (cfg.proxy_wallet if cfg else None)

    now = datetime.now(UTC).isoformat()
    lines = [
        "# Live API Validation",
        "",
        f"Verification timestamp (UTC): `{now}`",
        "",
        "## Endpoint",
        "",
        "`GET https://data-api.polymarket.com/trades`",
        "",
    ]

    if not account:
        lines += [
            "## Gate status",
            "",
            "**BLOCKED** — no verified public proxy wallet configured for `nagi777`.",
            "",
            "Facts and assumptions remain unverified in this environment.",
        ]
        args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    facts: list[str] = []
    assumptions: list[str] = []

    try:
        with httpx.Client(timeout=20.0) as client:
            base_status, base_body = _query(
                client,
                account=account,
                params={"offset": 0, "limit": 5, "takerOnly": "false"},
            )
            facts.append(f"status(offset=0,limit=5,takerOnly=false): {base_status}")
            if base_status != 200:
                raise RuntimeError(base_body[:500])

            payload = json.loads(base_body)
            if isinstance(payload, list):
                facts.append("response top-level type: list")
            else:
                assumptions.append(f"unexpected payload type: {type(payload).__name__}")
                payload = []

            if payload:
                sample = payload[0]
                facts.append(f"observed fields: {sorted(sample.keys())}")
                ts_unit = _infer_timestamp_unit(sample.get("timestamp"))
                facts.append(f"observed timestamp unit (by magnitude): {ts_unit}")
                facts.append(f"id present in sample: {'id' in sample}")

            ceiling_status, _ = _query(
                client,
                account=account,
                params={"offset": 10000, "limit": 1, "takerOnly": "false"},
            )
            facts.append(f"status(offset=10000,limit=1,takerOnly=false): {ceiling_status}")

            beyond_status, _ = _query(
                client,
                account=account,
                params={"offset": 10001, "limit": 1, "takerOnly": "false"},
            )
            facts.append(f"status(offset=10001,limit=1,takerOnly=false): {beyond_status}")

            now_sec = int(datetime.now(UTC).timestamp())
            window_status, _ = _query(
                client,
                account=account,
                params={
                    "offset": 0,
                    "limit": 5,
                    "takerOnly": "false",
                    "start": now_sec - 86400,
                    "end": now_sec,
                },
            )
            facts.append(f"status(with start/end window): {window_status}")
    except Exception as exc:  # pragma: no cover - network-dependent
        lines += [
            "## Gate status",
            "",
            f"**BLOCKED** — live query failed in this environment: `{type(exc).__name__}: {exc}`",
            "",
            "No API facts were fabricated. Run this command from a network-enabled environment.",
        ]
        args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    lines += ["## Observed facts", ""]
    lines.extend([f"- {item}" for item in facts] or ["- none"])
    lines += ["", "## Remaining assumptions / uncertainties", ""]
    lines.extend([f"- {item}" for item in assumptions] or ["- none"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
