# Contributing

Thanks for your interest in contributing to the COMSOL Multiphysics MCP Server.

## Reporting Issues

Open an issue at https://github.com/sparkyScientist/COMSOL_Multiphysics_MCP/issues with:

- COMSOL version and platform (macOS, Linux, Windows)
- Python version and conda environment details
- Steps to reproduce
- Full error traceback

## Adding New Tools

Each MCP tool lives in `src/tools/`. To add a new tool:

1. Create or edit a file in `src/tools/` (e.g., `src/tools/my_tool.py`)
2. Implement the tool function with clear docstrings
3. Register the tool in `src/server.py`
4. Add a test in `tests/`
5. Update the Tool Reference table in `README.md`

## Coding Style

- Follow PEP 8
- Use type hints for function signatures
- Use `mph.Client(port=...)` for COMSOL connections, never `mph.start()`
- Read port from `config.py` or `os.getenv("COMSOL_PORT", "2036")`
- Cast all Java API return values with `str()` before serialization
- Keep tool functions stateless where possible

## Pull Requests

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Run existing tests: `python -m pytest tests/`
4. Open a PR with a clear description of what changed and why

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
