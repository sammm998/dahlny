from __future__ import annotations

import re

import pytest

from app.config.settings import (
    load_label_grammar,
    load_models_config,
    load_reference_tables,
    load_thresholds,
)


def test_models_config_has_all_spec_tasks() -> None:
    cfg = load_models_config()
    for task_id in [f"T{i}" for i in range(1, 11)]:
        assert task_id in cfg.tasks, f"{task_id} saknas i models.yaml (SPEC 7.1)"


def test_t4_uses_other_model_than_t3() -> None:
    # SPEC 6.2.6 / 7.1: fullständighetskontrollen ska vara en oberoende andra läsning.
    cfg = load_models_config()
    assert cfg.task("T4").model != cfg.task("T3").model


def test_unknown_task_fails_loud() -> None:
    with pytest.raises(KeyError, match="T99"):
        load_models_config().task("T99")


def test_unknown_model_in_task_is_rejected() -> None:
    from app.config.settings import ModelsConfig

    raw = load_models_config().model_dump()
    raw["tasks"]["T1"]["model"] = "claude-does-not-exist"
    with pytest.raises(ValueError, match="claude-does-not-exist"):
        ModelsConfig.model_validate(raw)


@pytest.mark.parametrize("section", ["pipe", "object", "schematic_valve"])
def test_grammar_examples_parse(section: str) -> None:
    grammar = load_label_grammar()
    spec = getattr(grammar, section)
    assert spec.examples_ok, f"{section} saknar examples_ok"
    for example in spec.examples_ok:
        assert re.match(spec.pattern, example), f"{section}: {example!r} parsas inte"


def test_pipe_grammar_groups() -> None:
    m = re.match(load_label_grammar().pipe.pattern, "KV01-K1-15-W40")
    assert m is not None
    assert m.group("system") == "KV01"
    assert m.group("material") == "K1"
    assert m.group("dim") == "15"
    assert m.group("suffixes") == "-W40"  # okänt suffix behålls, tolkas aldrig bort


@pytest.mark.parametrize(
    ("pattern_key", "text", "group", "value"),
    [
        ("height.cl", "CL+2300", "mm", "2300"),
        ("height.vg", "VG+-828", "mm", "828"),
        ("slope", "1:100", "n", "100"),
    ],
)
def test_height_and_slope(pattern_key: str, text: str, group: str, value: str) -> None:
    m = re.match(load_label_grammar().all_patterns()[pattern_key], text)
    assert m is not None and m.group(group) == value


@pytest.mark.parametrize(
    ("index", "text"),
    [(0, "VS 21 - K1 - 20"), (1, "Ø110 PP"), (2, '3/4"')],
)
def test_alternative_patterns(index: int, text: str) -> None:
    assert re.match(load_label_grammar().alternatives[index], text)


def test_reference_tables_match_appendix_b() -> None:
    tables = load_reference_tables()
    assert len(tables.materials) == 20  # B.1
    assert len(tables.systems) == 15  # B.2
    assert tables.materials["E13"] == "PEM-rör, PN10"
    assert tables.material_ama["K1"].code == "PNU.311"


def test_thresholds_lookup() -> None:
    t = load_thresholds()
    assert t.get("scale.max_disagreement_fraction") == 0.01
    assert t.get("assign.max_unassigned_length_fraction") == 0.02
    with pytest.raises(KeyError):
        t.get("scale.does_not_exist")
