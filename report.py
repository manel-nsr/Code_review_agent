"""
report.py

Transforme la liste d'Issue fusionnées en un rapport Markdown lisible par
un humain. Le JSON reste disponible séparément pour intégration (ex: un
GitHub Action qui commenterait une PR automatiquement).
"""

from __future__ import annotations

from .analyzers import Issue
from .merger import compute_score

_SEVERITY_EMOJI = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🔵"}


def _line_str(issue: Issue) -> str:
    if issue.line is None:
        return "?"
    if isinstance(issue.line, (list, tuple)):
        return f"{issue.line[0]}-{issue.line[1]}"
    return str(issue.line)


def render_markdown(filepath: str, issues: list[Issue], llm_error: str | None = None) -> str:
    score = compute_score(issues)
    tool_count = sum(1 for i in issues if i.source != "llm")
    llm_count = sum(1 for i in issues if i.source == "llm")

    lines = [
        f"# Code Review Report — `{filepath}`",
        "",
        f"**Score global : {score}/100**",
        "",
        f"- Issues détectées par les outils statiques (Bandit/Flake8/Pylint) : {tool_count}",
        f"- Issues détectées par le raisonnement LLM (bugs logiques, autorisation, "
        f"performance, edge cases) : {llm_count}",
        "",
    ]

    if llm_error:
        lines += [
            "> ⚠️ **La revue LLM a échoué** — ce rapport ne contient que les résultats "
            "des outils statiques.",
            f"> Détail : {llm_error}",
            "",
        ]

    if not issues:
        lines.append("Aucun problème détecté. 🎉")
        return "\n".join(lines)

    lines.append("## Issues")
    lines.append("")

    for issue in issues:
        emoji = _SEVERITY_EMOJI.get(issue.severity, "⚪")
        lines += [
            f"### {emoji} [{issue.severity}] {issue.title}",
            f"- **Ligne** : {_line_str(issue)}",
            f"- **Catégorie** : {issue.category}",
            f"- **Source** : {issue.source}"
            + (f" ({issue.rule_id})" if issue.rule_id else ""),
            f"- **Pourquoi c'est un problème** : {issue.explanation}",
            f"- **Suggestion** : {issue.suggestion}",
            "",
        ]

    return "\n".join(lines)


def render_json(issues: list[Issue]) -> list[dict]:
    return [i.to_dict() for i in issues]
