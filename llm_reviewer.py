"""
llm_reviewer.py

Appelle le LLM et transforme sa réponse en objets Issue.

Pourquoi ne pas utiliser response_format={"type": "json_object"} ?
-> Certains endpoints Groq/modèles open-weight ne respectent pas ce mode
   de façon fiable pour un array JSON top-level (le mode "json_object"
   attend souvent un objet {}, pas un array []). Plutôt que de dépendre
   d'une fonctionnalité qui varie selon le modèle, on force le format
   dans le prompt et on parse défensivement côté client : on retire les
   éventuels ```json fences, on essaie json.loads, et si le modèle a
   entouré le JSON de texte parasite malgré la consigne, on extrait le
   premier bloc [...]. C'est moins élégant que de faire confiance à un
   mode strict, mais ça marche sur n'importe quel modèle/API compatible
   OpenAI, ce qui garde le projet portable (Groq, OpenAI, Anthropic...).
"""

from __future__ import annotations

import json
import re
from typing import Optional

from openai import OpenAI

from .analyzers import Issue
from .prompts import SYSTEM_PROMPT, build_user_prompt


def _extract_json_array(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    if text.startswith("["):
        return text
    match = re.search(r"\[.*\]", text, re.DOTALL)
    return match.group(0) if match else "[]"


def run_llm_review(
    code: str,
    bandit_raw: str,
    flake8_raw: str,
    pylint_raw: str,
    api_key: str,
    base_url: str = "https://api.groq.com/openai/v1",
    model: str = "llama-3.3-70b-versatile",
) -> tuple[list[Issue], Optional[str]]:
    """Retourne (issues, error). Si error n'est pas None, issues sera vide
    et le pipeline doit continuer avec seulement les résultats des linters
    plutôt que de planter tout le rapport pour une panne LLM."""
    client = OpenAI(api_key=api_key, base_url=base_url)
    user_prompt = build_user_prompt(code, bandit_raw, flake8_raw, pylint_raw)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        raw_content = response.choices[0].message.content
    except Exception as e:  # panne réseau / clé invalide / rate limit
        return [], f"Appel LLM échoué: {e}"

    try:
        parsed = json.loads(_extract_json_array(raw_content))
    except json.JSONDecodeError as e:
        return [], f"Réponse LLM non parsable en JSON: {e}\nContenu brut: {raw_content[:500]}"

    issues = []
    for item in parsed:
        try:
            issues.append(Issue(
                title=item["title"],
                severity=item.get("severity", "Medium"),
                category=item.get("category", "Logic Bug"),
                line=item.get("line"),
                explanation=item.get("explanation", ""),
                suggestion=item.get("suggestion", ""),
                source="llm",
            ))
        except KeyError:
            continue  # item malformé isolé : on l'ignore plutôt que de tout faire échouer

    return issues, None
