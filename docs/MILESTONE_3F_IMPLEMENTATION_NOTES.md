# Milestone 3F implementation notes

Stage 3F is implemented as an additive forensic layer over the already-validated Stage 3C materializer and frozen Stage 3D/3E models.

Key boundaries:

- The original August 7–13 discovery windows remain unchanged.
- The external July 24–30 windows are collected independently and are not used for fitting or tuning.
- Stage 3F imports the fixed Stage 3E HGB implementation so model hyperparameters cannot silently diverge.
- The transparent external comparator reuses the Stage 3D timing+inventory Ridge/logistic implementation.
- BTC permutation is performed only on held-out discovery-window rows; the trained model and non-BTC features remain unchanged.
- Joint BTC permutation uses one shared row permutation across all BTC fields to preserve their internal cross-feature structure while breaking alignment to the event state/outcome.
- The external confirmation decision is computed exclusively from the six predeclared gate booleans in the frozen protocol.

The Stage 3F evidence remains historical explanatory analysis. Passing the external gate would justify a separately frozen richer-model experiment; it would not by itself establish a deployable or profitable trading strategy.
