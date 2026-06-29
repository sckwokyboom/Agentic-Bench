import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "export_chain_snippets.py"
SPEC = importlib.util.spec_from_file_location("export_chain_snippets", SCRIPT)
exporter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = exporter
SPEC.loader.exec_module(exporter)


BUDGET = """\
#### 4.4.1.a Cluster: Entry.one path (2 chains)

**Entry-point:** `example.Entry.one`
**Primary representative:** `example.Test.first`

#### 4.4.1.b Cluster: Entry.two path (1 chains)

**Entry-point:** `example.Entry.two`
**Primary representative:** `example.Test.second`
"""

CHAINS = [
    {
        "test": {"fqn": "example.Test.first"},
        "steps": [
            {"callerFqn": "example.Test.first", "calleeFqn": "example.Entry.one"},
            {
                "callerFqn": "example.Entry.one",
                "calleeFqn": "example.Shared.call",
                "snippet": "void one() {\n    Shared.call(value);\n}",
            },
            {
                "callerFqn": "example.Shared.call",
                "calleeFqn": "example.Target.work",
                "snippet": "void call() {\n    Target.work(value);\n}",
            },
        ],
    },
    {
        "test": {"fqn": "example.Test.second"},
        "steps": [
            {"callerFqn": "example.Test.second", "calleeFqn": "example.Entry.two"},
            {
                "callerFqn": "example.Entry.two",
                "calleeFqn": "example.Shared.call",
                "snippet": "void two() {\n    Shared.call(other);\n}",
            },
            {
                "callerFqn": "example.Shared.call",
                "calleeFqn": "example.Target.work",
                "snippet": "duplicate body",
            },
        ],
    },
]


def test_collects_all_post_entry_edges_and_deduplicates_shared_tail():
    medoids = exporter.parse_medoids(BUDGET)
    steps = exporter.collect_unique_steps(medoids, CHAINS, "example.Target.work")

    assert [(s["callerFqn"], s["calleeFqn"]) for s in steps] == [
        ("example.Entry.one", "example.Shared.call"),
        ("example.Shared.call", "example.Target.work"),
        ("example.Entry.two", "example.Shared.call"),
    ]


def test_compact_snippet_keeps_signature_and_call_within_limit():
    snippet = "\n".join(
        ["void caller() {"] + [f"    int n{i} = {i};" for i in range(9)]
        + ["    target(n8);", "}"]
    )

    compact = exporter.compact_snippet(snippet, "example.Target.target", max_lines=8)

    assert compact.splitlines()[0] == "void caller() {"
    assert "target(n8);" in compact
    assert len(compact.splitlines()) <= 8


def test_render_never_includes_a_step_called_by_the_target():
    target_step = {
        "callerFqn": "example.Target.work",
        "calleeFqn": "example.Helper.next",
        "snippet": "void work() { Helper.next(); }",
    }

    with pytest.raises(ValueError, match="target method body"):
        exporter.render_block([target_step], "example.Target.work")


def test_render_uses_source_override_when_sidecar_did_not_locate_call():
    step = {
        "callerFqn": "example.Caller.call",
        "calleeFqn": "example.Target.work",
        "snippet": "(call site not located)",
    }
    overrides = {
        "example.Caller.call -> example.Target.work":
            "void call() {\n    Target.work();\n}",
    }

    block = exporter.render_block(
        [step], "example.Target.work", overrides=overrides
    )

    assert "Target.work();" in block
    assert "Call site not located" not in block


def test_insert_replaces_existing_block_idempotently():
    markdown = """\
## Clustered call chains (medoids)

chains

---

## Later
"""
    block = exporter.HEADING + "\n\nnew\n"

    once = exporter.insert_block(markdown, block)
    twice = exporter.insert_block(once, block)

    assert once == twice
    assert once.count(exporter.HEADING) == 1
    assert once.index(exporter.HEADING) < once.index("## Later")
