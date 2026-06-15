from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from aqsd.models import AnimeRule, Candidate
from aqsd.utils import contains_all_keywords, contains_any_keyword


def build_rules(config_rules: Iterable[AnimeRule | dict[str, Any]]) -> list[AnimeRule]:
    rules: list[AnimeRule] = []
    for rule in config_rules:
        if isinstance(rule, AnimeRule):
            rules.append(rule)
        else:
            rules.append(AnimeRule(**rule))
    return rules


def match_candidate(
    candidate: Candidate,
    rules: list[AnimeRule],
    profiles: dict[str, dict[str, Any]],
    default_category: str,
    default_save_path: str | None,
) -> Candidate | None:
    title = candidate.title

    for rule in rules:
        names = [rule.name, *rule.aliases]
        if not contains_any_keyword(title, names):
            continue

        if rule.include and not contains_all_keywords(title, rule.include):
            continue

        if rule.reject and contains_any_keyword(title, rule.reject):
            continue

        profile = profiles.get(rule.profile, {})

        must_include = profile.get("must_include", [])
        if must_include and not contains_all_keywords(title, must_include):
            continue

        profile_reject = profile.get("reject", [])
        if profile_reject and contains_any_keyword(title, profile_reject):
            continue

        if rule.allow_hevc is False and candidate.is_hevc:
            continue

        if rule.allow_dual_audio is False and candidate.has_dual_audio:
            continue

        if profile.get("allow_subtitled", True) is False and candidate.subtitle_type in {"embedded", "external"}:
            continue

        allow_other_group = profile.get("allow_other_group", True)
        if not allow_other_group and rule.prefer_groups and candidate.group not in rule.prefer_groups:
            continue

        candidate.matched_rule_name = rule.name
        candidate.anime_name = rule.name
        candidate.category = rule.category or default_category
        candidate.save_path = rule.save_path or default_save_path
        return candidate

    return None
