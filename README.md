# Agents

A collection of small, self-contained AI agents. Each agent lives in its own folder with its own dependencies, config, `Makefile` and README. You can run, change or delete one without touching the others.

## Agents

| Agent | What it does | Interfaces |
|---|---|---|
| [`expense-agent`](expense-agent/) | Tracks expenses in SQLite through chat and tool calls. Deletes need your confirmation. | Web chat, terminal, HTTP API |

Run `make list` from the repo root to print this list from the folders themselves.

## Quick start

Every agent follows the same steps:

```bash
cd <agent>          # e.g. cd expense-agent
make help           # see what the agent offers
make setup          # creates .venv, installs dependencies, creates .env
# edit .env and set any keys
make run            # or the agent's own target, e.g. make web
```

You can also run an agent from the repo root without changing directory:

```bash
make -C expense-agent web
```

## Repository layout

```
agents/
  README.md         This file: the index and the conventions.
  Makefile          Repo-level helpers: list, new.
  LICENSE           MIT, covers the whole repo.
  .gitignore        Shared ignores: .env, .venv, *.db, caches.
  _template/        Starting point for a new agent. Not an agent itself.
  <agent-name>/     One folder per agent. Self-contained.
```

## Add a new agent

```bash
make new NAME=my-agent
```

This copies `_template/` to `my-agent/`. Then:

1. Replace the stub in `main.py` with your agent. Put the agent's name and purpose in its `README.md`.
2. Declare dependencies in the agent's `requirements.txt` and every setting in its `.env.example`.
3. Add a row to the **Agents** table above.

`NAME` must use lowercase letters, digits and dashes.

## Conventions

These keep the agents consistent and let a new person run any of them the same way.

- **Self-contained.** An agent folder has its own `requirements.txt`, `.env.example`, `Makefile`, `README.md` and `.venv`. Agents don't import from each other. If two agents need the same code, copy it first. Add a shared package only when the duplication really hurts.
- **Same entry points.** Each `Makefile` provides `help`, `setup`, `run` (or a more specific target), `test` and `clean`. `make setup` must work on a fresh clone.
- **Secrets stay local.** Keys go in `.env`, which is git-ignored. Commit only `.env.example`, with placeholder values.
- **Local data stays local.** Databases and other runtime files (`*.db`) are git-ignored.
- **Document each agent.** Its README says what it does, how to configure it, how to run it, and what its limits are (for example, no login on a local web page).
- **Safe by design.** The model asks for actions and the code validates and runs them. Destructive actions need a confirmation enforced in code, not in the prompt.
- **Tests that cost money are labelled.** Prefer tests with fakes. If an agent has tests that call a paid or rate-limited model, its README says so. (`expense-agent`'s `make test` is one of these: it runs live-model cases.)

## License

[MIT](LICENSE)
