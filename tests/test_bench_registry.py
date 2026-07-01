import pytest

from abench.bench import registry
from abench.bench.base import GradeResult


class _Dummy:
    id = "dummy-x"

    def load(self, dataset, subset=None):
        return []

    def materialize(self, view, workdir):
        pass

    def grade(self, inst, source_diff, workdir):
        return GradeResult(resolved=None, evaluator="d", standard_protocol=True)


def test_register_and_get():
    d = _Dummy()
    registry.register(d)
    assert registry.get_adapter("dummy-x") is d
    assert "dummy-x" in registry.available()


def test_unknown_adapter_raises():
    with pytest.raises(KeyError):
        registry.get_adapter("nope-not-real")
