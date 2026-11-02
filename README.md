# Spot Heating Planner

A Home Assistant integration that keeps an unheated or lightly heated space
(a garage, storage building, cottage or crawl space) frost-free and dry at the
lowest electricity cost. It learns how the space warms and cools, then plans
heating hour by hour on spot prices and the weather forecast.

> Work in progress: not yet ready for use.

## Development

```bash
uv sync                 # Python 3.13 and the dev tools
uv run pytest           # tests
uv run ruff check .     # lint
uv run ruff format .    # format
uv run mypy             # strict type check
uv run pre-commit install   # run the checks before every commit
```

## License

MIT
