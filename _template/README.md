# {{NAME}}

One sentence: what this agent does and what it talks to (model provider, tools, data).

```
you> an example request   -> tool_that_runs
```

## Quick start

```bash
make setup          # creates .venv, installs dependencies, creates .env
# edit .env and set any keys
make run
```

## Configuration (`.env`)

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `EXAMPLE_API_KEY` | yes | none | Describe it |

## How to operate

Describe each way to run the agent (terminal, web, API) and the `make` targets.

## Project layout

```
main.py     Entry point.
```

## Notes

- Anything a user must know before relying on it: limits, safety, known gaps.
