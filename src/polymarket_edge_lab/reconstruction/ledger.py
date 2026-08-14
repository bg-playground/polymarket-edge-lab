from __future__ import annotations

from collections import defaultdict

from polymarket_edge_lab.models.reconstruction import LedgerEntry, OutcomeSide
from polymarket_edge_lab.models.trade import NormalizedTrade

_UP = {"UP", "YES", "LONG"}
_DOWN = {"DOWN", "NO", "SHORT"}


def _normalize_outcome(outcome: str) -> str:
    return outcome.strip().upper()


def classify_binary_market(
    outcomes: set[str],
    *,
    history_complete: bool,
) -> tuple[bool, str | None, dict[str, OutcomeSide]]:
    if not history_complete:
        return False, "unresolved_history_completeness", {}
    if len(outcomes) != 2:
        return False, f"expected_2_outcomes_found_{len(outcomes)}", {}

    normalized = {_normalize_outcome(value): value for value in outcomes}
    up_match = [v for k, v in normalized.items() if k in _UP]
    down_match = [v for k, v in normalized.items() if k in _DOWN]
    if len(up_match) != 1 or len(down_match) != 1:
        return False, "ambiguous_non_complementary_outcomes", {}

    mapping: dict[str, OutcomeSide] = {up_match[0]: "UP", down_match[0]: "DOWN"}
    return True, None, mapping


def build_canonical_ledger(
    trades: list[NormalizedTrade],
    *,
    complete_market_ids: set[str] | None = None,
) -> list[LedgerEntry]:
    complete_market_ids = complete_market_ids if complete_market_ids is not None else set()
    sorted_trades = sorted(trades, key=lambda t: (t.timestamp, t.source_trade_id))

    outcomes_by_market: dict[str, set[str]] = defaultdict(set)
    for trade in sorted_trades:
        outcomes_by_market[trade.market_id].add(trade.outcome)

    eligibility: dict[str, tuple[bool, str | None, dict[str, OutcomeSide]]] = {}
    for market_id, outcomes in outcomes_by_market.items():
        eligibility[market_id] = classify_binary_market(
            outcomes,
            history_complete=market_id in complete_market_ids if complete_market_ids else True,
        )

    market_seq: dict[str, int] = defaultdict(int)
    ledger: list[LedgerEntry] = []

    for fill_index, trade in enumerate(sorted_trades, start=1):
        market_seq[trade.market_id] += 1
        eligible, reason, mapping = eligibility[trade.market_id]
        normalized_outcome_side = mapping.get(trade.outcome)
        outcome_side_reason = None
        if eligible and normalized_outcome_side is None:
            outcome_side_reason = "outcome_not_in_binary_mapping"
        if not eligible:
            outcome_side_reason = reason

        raw_page_path = trade.raw_extra.get("_raw_page_path")
        raw_page_hash = trade.raw_extra.get("_raw_page_hash")
        page_offset = trade.raw_extra.get("_page_offset")
        record_index = trade.raw_extra.get("_record_index")

        ledger.append(
            LedgerEntry(
                source_trade_id=trade.source_trade_id,
                account=trade.account,
                market_id=trade.market_id,
                asset_id=trade.asset_id,
                outcome=trade.outcome,
                side=trade.side,
                timestamp=trade.timestamp,
                price=trade.price,
                shares=trade.shares,
                notional=trade.notional,
                transaction_hash=trade.transaction_hash,
                outcome_index=trade.outcome_index,
                slug=trade.slug,
                event_slug=trade.event_slug,
                title=trade.title,
                raw_page_path=str(raw_page_path) if raw_page_path is not None else None,
                raw_page_hash=str(raw_page_hash) if raw_page_hash is not None else None,
                page_offset=int(page_offset)
                if isinstance(page_offset, int | float | str)
                else None,
                record_index=int(record_index)
                if isinstance(record_index, int | float | str)
                else None,
                market_sequence_number=market_seq[trade.market_id],
                fill_sequence_number=fill_index,
                eligible_binary_market=eligible,
                market_exclusion_reason=reason,
                normalized_outcome_side=normalized_outcome_side,
                outcome_side_reason=outcome_side_reason,
            )
        )
    return ledger
