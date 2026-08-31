# Contributing

Thanks for your interest in the Agent Knowledge Base. This is a research/design
repo, so contributions are primarily documentation, research, and architecture —
but the same workflow applies once implementation starts.

## Workflow (linear history, protected `main`)

We keep `main` linear and protected. All changes land via **squash-merged PRs**.

1. **Create a branch** off `main`:
   - `docs/*` for documentation/research
   - `feat/*` for features
   - `fix/*` for bug fixes
   - `chore/*` for maintenance

   ```bash
   git checkout -b docs/media-extraction-update
   ```

2. **Make your changes**, keeping them focused on one concern. Follow the
   conventional-commit subject line in your PR title (e.g. `docs: add 2026
   embedding research`).

3. **Run the checks** (when present):
   ```bash
   uv run ruff check .
   uv run pytest
   ```
   For a docs-only repo, ensure markdown links resolve and claims are cited.

4. **Push and open a PR** using the template:
   ```bash
   git push -u origin <branch>
   gh pr create
   ```

5. **Get a review.** At least one approving review is required to merge.

6. **Merge with squash.** The PR is squash-merged into `main`, keeping history
   linear. The PR title becomes the squashed commit message.

## Branch protection

`main` is protected: no direct pushes, required pull-request reviews, required
status checks (when CI is configured), and history is linear via squash merges.

## Conventions

- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) —
  `type(scope): subject`.
- **No direct pushes to `main`.**
- **No `pip`** — use `uv` (`.venv` in any Python project root).
- **No PowerShell.**
- Research/design claims **must be cited** (URLs) in `docs/`.

## Issues

Use GitHub Issues for bugs and feature requests (this repo uses GitHub Issues,
unlike some others). If you're reporting a bug, include a clear reproduction.

## Code of conduct

Be respectful and constructive. This is a small personal project; treat
contributors the way you'd want to be treated.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
