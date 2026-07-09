#!/usr/bin/env python3
"""
review.py — CLI de l'agent de revue de code.

Usage:
    python review.py samples/user_management.py
    python review.py samples/user_management.py --out report.md --json report.json
    python review.py samples/user_management.py --no-llm   # linters seuls, pas d'appel API

Variable d'environnement requise pour la partie LLM :
    GROQ_API_KEY
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from agent.analyzers import run_all
from agent.llm_reviewer import run_llm_review
from agent.merger import merge_results
from agent.report import render_markdown, render_json


def main():
    parser = argparse.ArgumentParser(description="Agent de revue de code Python.")
    parser.add_argument("filepath", help="Fichier Python à analyser")
    parser.add_argument("--out", default="report.md", help="Chemin du rapport Markdown")
    parser.add_argument("--json", default=None, help="Chemin optionnel pour le rapport JSON")
    parser.add_argument("--no-llm", action="store_true", help="Désactive l'appel LLM (linters seuls)")
    parser.add_argument("--model", default="llama-3.3-70b-versatile", help="Modèle Groq à utiliser")
    args = parser.parse_args()

    if not os.path.isfile(args.filepath):
        print(f"Fichier introuvable : {args.filepath}", file=sys.stderr)
        sys.exit(1)

    with open(args.filepath, "r", encoding="utf-8") as f:
        code = f.read()

    print(f"→ Analyse statique de {args.filepath} (Bandit, Flake8, Pylint)...")
    tool_result = run_all(args.filepath)
    tool_issues = tool_result["issues"]
    print(f"  {len(tool_issues)} issue(s) trouvée(s) par les outils.")

    llm_issues = []
    llm_error = None

    if not args.no_llm:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            llm_error = "GROQ_API_KEY non définie dans l'environnement."
            print(f"  ⚠️ {llm_error} — passage en mode linters seuls.")
        else:
            print("→ Revue LLM (bugs logiques, autorisation, performance, edge cases)...")
            llm_issues, llm_error = run_llm_review(
                code=code,
                bandit_raw=tool_result["raw"]["bandit"],
                flake8_raw=tool_result["raw"]["flake8"],
                pylint_raw=tool_result["raw"]["pylint"],
                api_key=api_key,
                model=args.model,
            )
            if llm_error:
                print(f"  ⚠️ {llm_error}")
            else:
                print(f"  {len(llm_issues)} issue(s) trouvée(s) par le LLM.")

    merged = merge_results(tool_issues, llm_issues)

    markdown = render_markdown(args.filepath, merged, llm_error)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(markdown)
    print(f"→ Rapport Markdown écrit dans {args.out}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(render_json(merged), f, indent=2, ensure_ascii=False)
        print(f"→ Rapport JSON écrit dans {args.json}")


if __name__ == "__main__":
    main()
