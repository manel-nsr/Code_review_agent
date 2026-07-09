"""
analyzers.py

Exécute les outils d'analyse statique (Bandit, Flake8, Pylint) sur un
fichier Python et normalise leurs sorties en une liste d'objets Issue
communs, indépendants de l'outil qui les a produits.

Pourquoi normaliser plutôt que garder le format brut de chaque outil ?
-> Bandit, Flake8 et Pylint ont trois formats de sortie complètement
   différents (JSON imbriqué, texte "fichier:ligne:col: code message",
   JSON à plat). Si on les garde bruts, le merge avec les résultats du
   LLM (étape 3) devient un cauchemar de cas particuliers. On paie le
   coût de la normalisation une fois, ici, pour que tout le reste du
   pipeline (merge, scoring, rapport) manipule un seul type d'objet.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Issue:
    title: str
    severity: str          # Critical | High | Medium | Low
    category: str          # Security | Style | Bug | Performance | ...
    line: Optional[int]
    explanation: str
    suggestion: str
    source: str             # "bandit" | "flake8" | "pylint" | "llm"
    rule_id: Optional[str] = None  # ex: "B105", "E501", "C0116" — utile pour dédupliquer

    def to_dict(self):
        return asdict(self)


def _run(cmd: list[str]) -> str:
    """Exécute une commande et retourne stdout, même si le code de sortie
    n'est pas 0 (les linters retournent souvent un exit code != 0 quand
    ils trouvent des problèmes — ce n'est pas une erreur d'exécution)."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout


# --- Bandit -----------------------------------------------------------

_BANDIT_SEVERITY_MAP = {"HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"}


def run_bandit(filepath: str) -> tuple[list[Issue], str]:
    """Retourne (issues normalisées, sortie brute) pour Bandit."""
    raw = _run(["bandit", "-f", "json", filepath])
    issues: list[Issue] = []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return issues, raw

    for r in data.get("results", []):
        issues.append(Issue(
            title=r.get("test_name", "Bandit finding"),
            severity=_BANDIT_SEVERITY_MAP.get(r.get("issue_severity", "LOW"), "Low"),
            category="Security",
            line=r.get("line_number"),
            explanation=r.get("issue_text", "").strip(),
            suggestion="Voir la documentation Bandit pour ce test: "
                       f"https://bandit.readthedocs.io/en/latest/plugins/{r.get('test_id', '').lower()}.html",
            source="bandit",
            rule_id=r.get("test_id"),
        ))
    return issues, raw


# --- Flake8 -------------------------------------------------------------

_FLAKE8_SEVERITY = {
    "E9": "High",   # erreurs de syntaxe
    "F82": "High",  # noms indéfinis
}


def _flake8_severity(code: str) -> str:
    for prefix, sev in _FLAKE8_SEVERITY.items():
        if code.startswith(prefix):
            return sev
    if code.startswith("E") or code.startswith("F"):
        return "Medium"
    return "Low"  # warnings de style (W...)


def run_flake8(filepath: str) -> tuple[list[Issue], str]:
    raw = _run(["flake8", "--max-line-length=110", filepath])
    issues: list[Issue] = []
    for line in raw.strip().splitlines():
        # format: path:line:col: CODE message
        try:
            _, lineno, _col, rest = line.split(":", 3)
            code, message = rest.strip().split(" ", 1)
        except ValueError:
            continue
        issues.append(Issue(
            title=message.strip(),
            severity=_flake8_severity(code),
            category="Style",
            line=int(lineno),
            explanation=f"Flake8 [{code}]: {message.strip()}",
            suggestion="Corriger selon la convention PEP8 associée à ce code.",
            source="flake8",
            rule_id=code,
        ))
    return issues, raw


# --- Pylint ---------------------------------------------------------------

_PYLINT_SEVERITY = {
    "E": "High",      # Error
    "F": "Critical",  # Fatal
    "W": "Medium",    # Warning
    "C": "Low",       # Convention
    "R": "Low",       # Refactor
}


def run_pylint(filepath: str) -> tuple[list[Issue], str]:
    raw = _run(["pylint", "--output-format=json", filepath])
    issues: list[Issue] = []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return issues, raw

    for r in data:
        code = r.get("message-id", "")
        issues.append(Issue(
            title=r.get("symbol", "Pylint finding"),
            severity=_PYLINT_SEVERITY.get(code[:1], "Low"),
            category="Code Quality",
            line=r.get("line"),
            explanation=r.get("message", ""),
            suggestion="Voir la règle Pylint correspondante: "
                       f"https://pylint.pycqa.org/en/latest/user_guide/messages/{r.get('symbol','')}.html",
            source="pylint",
            rule_id=code,
        ))
    return issues, raw


def run_all(filepath: str) -> dict:
    """Lance les trois outils et retourne un dict avec issues normalisées
    ET sorties brutes (les brutes servent de contexte pour le LLM)."""
    bandit_issues, bandit_raw = run_bandit(filepath)
    flake8_issues, flake8_raw = run_flake8(filepath)
    pylint_issues, pylint_raw = run_pylint(filepath)

    return {
        "issues": bandit_issues + flake8_issues + pylint_issues,
        "raw": {
            "bandit": bandit_raw,
            "flake8": flake8_raw,
            "pylint": pylint_raw,
        },
    }
