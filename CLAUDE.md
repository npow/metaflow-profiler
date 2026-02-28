# metaflow-profiler

Interactive flamegraph profiling for Metaflow steps. Wraps any step with `@profile_card`
to collect call-stack + resource data and render a self-contained HTML card.

## Architecture

Layers (dependencies flow downward only):

```
Decorator   — src/.../plugins/profile_decorator.py
    ↓
Card        — src/.../plugins/cards/profile_card/card.py
    ↓
Registry    — src/.../plugins/profilers/__init__.py
    ↓
Backends    — src/.../plugins/profilers/{pyinstrument,cprofile_backend}.py
    ↓
ABC         — src/.../plugins/profiler.py
```

**Rule: no upward imports.** A backend must never import from the decorator or card layer.

## Key files

| What | Where |
|------|-------|
| Abstract interface | `src/metaflow_extensions/profiler/plugins/profiler.py` |
| Backend registry | `src/metaflow_extensions/profiler/plugins/profilers/__init__.py` |
| pyinstrument backend | `src/metaflow_extensions/profiler/plugins/profilers/pyinstrument.py` |
| cProfile backend | `src/metaflow_extensions/profiler/plugins/profilers/cprofile_backend.py` |
| Step decorator | `src/metaflow_extensions/profiler/plugins/profile_decorator.py` |
| Card renderer | `src/metaflow_extensions/profiler/plugins/cards/profile_card/card.py` |
| Plugin registration | `src/metaflow_extensions/profiler/plugins/mfextinit_profiler.py` |

## Commands

```bash
# Install (editable)
pip install -e ".[pyinstrument,dev]"

# Lint
ruff check src/ tests/

# Type check
mypy src/

# Unit tests
pytest tests/unit/

# Structural tests (enforce architecture)
pytest tests/structural/ -m structural
```

## Adding a new backend

1. Create `src/metaflow_extensions/profiler/plugins/profilers/mybackend.py`
2. Subclass `ProfilerBackend`, set `name = "mybackend"`
3. Implement `is_available()`, `start()`, `stop() -> ProfileData`
4. Decorate the class with `@register`
5. Import it in `profilers/__init__.py`

The backend may only import from:
- `..profiler` (ABC + ProfileData)
- Standard library
- Its own optional third-party dependency
