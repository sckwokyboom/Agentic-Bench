from abench.bench.base import Anchors, EnvSpec, Instance, TaskSpec
from abench.bench.expand import BenchRun, expand_plan
from abench.config import BenchmarkCfg, Condition, Experiment


def _exp(reps: int) -> Experiment:
    return Experiment(
        name="t",
        benchmark=BenchmarkCfg(adapter="smoke"),
        task_prompt="p",
        system_prompt="s",
        model="m",
        output_dir="out",
        repetitions=reps,
        conditions=[Condition(name="baseline"), Condition(name="alt")],
    )


def _inst(i: int) -> Instance:
    return Instance(
        instance_id=f"i{i}",
        repo="r",
        task=TaskSpec(prompt_text="x"),
        anchors=Anchors(),
        env=EnvSpec(image="none", build_system="none"),
    )


def test_expand_counts_instances_x_conditions_x_reps():
    exp = _exp(reps=3)
    runs = expand_plan(exp, [_inst(0), _inst(1)])
    assert len(runs) == 2 * 2 * 3
    assert isinstance(runs[0], BenchRun)
    assert {r.rep for r in runs} == {0, 1, 2}
    assert {r.condition.name for r in runs} == {"baseline", "alt"}
    assert {r.instance.instance_id for r in runs} == {"i0", "i1"}


def test_expand_empty_instances_is_empty():
    assert expand_plan(_exp(reps=2), []) == []
