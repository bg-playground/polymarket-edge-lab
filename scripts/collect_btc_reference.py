from __future__ import annotations

import argparse
from pathlib import Path

from polymarket_edge_lab.data.btc_reference import collect_coinbase_btc_usd, write_provenance


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect public BTC-USD reference candles")
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    args = parser.parse_args()
    candles, provenance = collect_coinbase_btc_usd(
        start_epoch=args.start,
        end_epoch=args.end,
        raw_path=args.raw,
    )
    write_provenance(args.provenance, provenance)
    print(f"collected {len(candles)} BTC-USD candles at 60-second resolution")
    print("15s/30s BTC features must remain disabled/null at this achieved resolution")


if __name__ == "__main__":
    main()
