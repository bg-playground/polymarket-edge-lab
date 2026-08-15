# Milestone 3G implementation notes

Stage 3G introduces a new materialization path rather than modifying the Stage 3C contemporaneous panel. FIFO labels are rebuilt while account state is snapshotted before the fill that completes each pair.

Key implementation constraints:

- the completing fill is not applied to inventory or rolling activity before its snapshot;
- deterministic `(timestamp, fill_sequence_number)` ordering governs same-timestamp availability;
- target FIFO lag is retained only as `lag_seconds_label_only` and is not a model feature;
- Stage 3G timing predictors are limited to market elapsed/remaining time;
- BTC features continue to use candles observable at or before prediction time;
- the Stage 3E HGB implementation and fixed parameters are reused directly;
- external July 10–16 rows are scored only after fitting on the complete August discovery panel.

The empirical workflow fails before model evaluation if the pre-event provenance audit detects a target/prior ordering or BTC reference-time violation.