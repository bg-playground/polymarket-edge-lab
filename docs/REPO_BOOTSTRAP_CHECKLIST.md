# Repository Bootstrap Checklist

- [ ] Create a new GitHub repository named `polymarket-edge-lab`.
- [ ] Upload or push this starter repository.
- [ ] Confirm `docs/RESEARCH_PLAN.md` is present.
- [ ] Commit the bootstrap as the initial known-good state.
- [ ] Create a Python 3.12 virtual environment.
- [ ] Run `pip install -e ".[dev]"`.
- [ ] Run `ruff check .`.
- [ ] Run `ruff format --check .`.
- [ ] Run `mypy src`.
- [ ] Run `pytest`.
- [ ] Enable GitHub Actions and confirm CI passes.
- [ ] Open `docs/MILESTONE_1_COPILOT_PROMPT.md`.
- [ ] Give that prompt to Copilot Agent.
- [ ] Review Copilot's API assumptions before merging.
- [ ] Require tests before accepting the PR.
- [ ] Tag or commit the completed Milestone 1 state before starting inventory reconstruction.
