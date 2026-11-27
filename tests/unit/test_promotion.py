from __future__ import annotations

from bmip.ml.registry import promotion_plan


def test_promotion_plan_accepts_a_better_challenger_and_archives_old_champion():
    result = promotion_plan(
        gate_pass=True,
        champion_before="2",
        candidate_version="4",
    )

    assert result == {
        "decision": "promoted",
        "champion_before": "2",
        "champion_after": "4",
        "archived_version": "2",
    }


def test_promotion_plan_rejects_a_worse_challenger_and_keeps_champion():
    result = promotion_plan(
        gate_pass=False,
        champion_before="2",
        candidate_version="4",
    )

    assert result["decision"] == "rejected"
    assert result["champion_after"] == "2"
    assert result["archived_version"] is None


def test_promotion_plan_handles_the_first_champion():
    result = promotion_plan(
        gate_pass=True,
        champion_before=None,
        candidate_version="1",
    )

    assert result["champion_after"] == "1"
    assert result["archived_version"] is None
