"""
merger.py

Fusionne les issues des linters et du LLM en un seul rapport, trie par
sévérité, et calcule un score global sur 100.

Pourquoi une déduplication "best effort" plutôt que stricte ?
-> Le prompt demande déjà au LLM de ne pas répéter les linters, donc en
   théorie il ne devrait pas y avoir de doublons. Mais les LLM ne suivent
   pas toujours les consignes à 100%. Plutôt que de faire confiance
   aveuglément, on applique un filtre de sécurité : si une issue LLM
   tombe sur la même ligne (+/- 1) qu'une issue déjà remontée par un
   outil, on la considère comme un doublon probable et on la retire.
   C'est volontairement conservateur (on préfère perdre une issue LLM
   limite plutôt que polluer le rapport de doublons).
"""

from __future__ import annotations

from .analyzers import Issue

_SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
_SEVERITY_PENALTY = {"Critical": 25, "High": 15, "Medium": 7, "Low": 2}


def _issue_line_numbers(issue: Issue) -> set[int]:
    if issue.line is None:
        return set()
    if isinstance(issue.line, (list, tuple)):
        return set(range(issue.line[0], issue.line[1] + 1))
    return {issue.line}


_RESOURCE_MGMT_RULE_IDS = {"R1732", "W1514"}  # consider-using-with, unspecified-encoding

def _is_likely_duplicate(llm_issue: Issue, tool_issues: list[Issue]) -> bool:
    llm_lines = _issue_line_numbers(llm_issue)
    llm_cat = llm_issue.category.lower()
    for t in tool_issues:
        tool_lines = _issue_line_numbers(t)
        same_neighborhood = llm_lines and tool_lines and any(
            abs(a - b) <= 1 for a in llm_lines for b in tool_lines
        )
        if not same_neighborhood:
            continue
        if t.category == "Security" and "security" in llm_cat:
            return True
        if llm_cat == "resource management" and (
            t.rule_id in _RESOURCE_MGMT_RULE_IDS or t.category == "Resource Management"
        ):
            return True
    return False


def _sort_line(issue: Issue) -> int:
    """Normalise issue.line (int OU [start, end]) en un seul entier pour le tri."""
    if issue.line is None:
        return 0
    if isinstance(issue.line, (list, tuple)):
        return issue.line[0]
    return issue.line


def merge_results(tool_issues: list[Issue], llm_issues: list[Issue]) -> list[Issue]:
    filtered_llm = [i for i in llm_issues if not _is_likely_duplicate(i, tool_issues)]
    merged = tool_issues + filtered_llm
    merged.sort(key=lambda i: (_SEVERITY_ORDER.get(i.severity, 4), _sort_line(i)))
    return merged


_SEVERITY_CAP = {"Critical": 40, "High": 30, "Medium": 20, "Low": 10}


def compute_score(issues: list[Issue]) -> int:
    """Score sur 100 avec rendements décroissants par catégorie de sévérité.

    Pourquoi pas une simple somme de pénalités (100 - somme) ?
    -> Testé en pratique : un fichier avec 26 problèmes de style "Low" (des
       vétilles Pylint comme des docstrings manquantes) faisait tomber le
       score à 0, exactement comme un fichier avec 26 injections SQL
       critiques. Le score devenait binaire et inutile dès qu'un fichier
       avait beaucoup de bruit de style. On plafonne donc la pénalité totale
       par palier de sévérité (ex: les "Low" ne peuvent jamais coûter plus
       de 10 points au total, peu importe qu'il y en ait 5 ou 50), pour que
       le score reflète surtout la gravité, pas le volume de bruit.
    """
    by_severity: dict[str, int] = {}
    for issue in issues:
        by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1

    total_penalty = 0
    for severity, count in by_severity.items():
        per_issue = _SEVERITY_PENALTY.get(severity, 2)
        cap = _SEVERITY_CAP.get(severity, 10)
        total_penalty += min(count * per_issue, cap)

    return max(0, 100 - total_penalty)
