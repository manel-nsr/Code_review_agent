# Code_review_agent
# Agent de revue de code Python

## Ce que j'ai construit et comment ça marche

Un agent de revue de code qui combine deux approches complémentaires :

1. **Analyse statique déterministe** — Bandit (sécurité), Flake8 (style/PEP8), Pylint
   (qualité de code) tournent sur le fichier et leurs sorties (JSON, texte, JSON) sont
   normalisées en un seul type d'objet `Issue` commun (titre, sévérité, catégorie, ligne,
   explication, suggestion, source, rule_id).
2. **Revue par LLM** — le code + les résultats des 3 linters sont envoyés à un LLM
   (Llama 3.3 70B via l'API Groq) avec un prompt qui lui interdit explicitement de
   répéter ce que les linters ont déjà trouvé. Son seul travail : détecter ce qu'un
   outil déterministe ne peut structurellement pas voir — bugs de logique, autorisation
   manquante, failles métier, problèmes de performance, gestion de ressources,
   concurrence — parce que ça demande de comprendre l'*intention* du code, pas juste sa
   syntaxe.

Les résultats des deux sources sont ensuite fusionnés (`merger.py`), dédupliqués
(best-effort : une issue LLM tombant sur la même ligne ±1 qu'une issue déjà remontée par
un outil, dans une catégorie qui se chevauche sémantiquement, est écartée), triés par
sévérité, et un score global sur 100 est calculé avec des pénalités plafonnées par
palier de sévérité (pour éviter qu'un fichier bruyant en style noie un fichier avec de
vraies failles critiques). Un rapport Markdown lisible + un export JSON sont générés.

### Architecture
```
review.py             → CLI, point d'entrée
agent/
  analyzers.py         → wrappers Bandit/Flake8/Pylint + normalisation en Issue
  prompts.py           → system prompt + construction du prompt utilisateur pour le LLM
  llm_reviewer.py      → appel API + parsing défensif de la réponse JSON
  merger.py            → fusion, déduplication, calcul du score
  report.py            → rendu Markdown + JSON
```

## Comment l'utiliser

Installer les dépendances :
```bash
pip install bandit flake8 pylint openai
```

Définir la clé API (Groq, ou tout endpoint compatible OpenAI) :
```bash
export GROQ_API_KEY="ta_clé"
```

Lancer la revue :
```bash
python review.py samples/user_management.py
python review.py samples/user_management.py --out report.md --json report.json
python review.py samples/user_management.py --no-llm   # linters seuls, sans appel API
python review.py samples/user_management.py --model llama-3.3-70b-versatile
```

## Outils, modèles et librairies utilisés

- **Bandit** — détection de vulnérabilités de sécurité Python (injections, secrets en
  dur, usage dangereux de `eval`/`subprocess`, hash faibles, etc.)
- **Flake8** — conformité PEP8 / style
- **Pylint** — qualité de code générale (conventions, refactoring, erreurs probables)
- **Llama 3.3 70B Versatile** via l'**API Groq** (endpoint compatible OpenAI) pour la
  couche de raisonnement contextuel
- **openai** (SDK Python) — utilisé uniquement comme client HTTP compatible, pas
  d'usage d'OpenAI directement
- Format d'échange : JSON strict imposé par prompt plutôt que par `response_format`,
  car ce mode n'est pas fiable pour un array JSON top-level sur tous les
  endpoints/modèles compatibles OpenAI

## Exemple : revue sur du code réel

Fichier testé : `samples/user_management.py` — module de gestion utilisateurs avec
authentification, reset de mot de passe, rapports de ventes, import en masse.

**Résultat** : 46 issues des outils statiques + 5-6 issues du LLM selon le run.
Score global : **15/100** (voir section "Défis" ci-dessous pour l'évolution 40 → 15).

Extrait du rapport généré :

| Sévérité | Titre | Ligne | Source |
|---|---|---|---|
| 🔴 Critical | Missing Authorization in reset_password | 70 | llm |
| 🟠 High | Use of weak MD5 hash | 42 | bandit (B324) |
| 🟠 High | shell=True subprocess (injection) | 178 | bandit (B602) |
| 🟡 Medium | N+1 query pattern dans get_all_orders_for_users | 107 | llm |
| 🟡 Medium | Division par zéro potentielle | 128 | llm |
| 🟡 Medium | Discount négatif si %>100 | 133 | llm |

Le rapport complet est disponible dans `report.md` / `report2.json` à la racine du repo.

Exemples représentatifs de ce que le LLM a trouvé et que les linters ne pouvaient pas
voir (raisonnement contextuel, pas pattern matching) :
- **N+1 query** (`get_all_orders_for_users`) — boucle qui exécute une requête SQL par
  utilisateur au lieu d'un seul `IN (...)`.
- **Division par zéro** (`calculate_average_order_value`) — aucune vérification que la
  liste `orders` n'est pas vide avant de diviser.
- **Discount négatif** (`apply_discount`) — aucune validation que le pourcentage de
  réduction est ≤ 100.
- **Autorisation manquante** (`reset_password`) — n'importe qui peut réinitialiser le
  mot de passe de n'importe quel utilisateur, aucune vérification d'identité.

## Défis rencontrés et pistes d'amélioration

**Faux négatif initial sur l'autorisation** — la première version du prompt ne trouvait
pas `reset_password()`, pourtant l'exemple typique de faille "invisible pour un linter,
visible seulement par raisonnement contextuel" que le projet est censé cibler. Corrigé
en rendant le prompt plus directif : consigne explicite de parcourir systématiquement
chaque fonction modifiant un état sensible et de vérifier s'il existe un contrôle
d'autorisation, plus une checklist finale avant de répondre. Testé sur 3 runs
consécutifs après correction : la faille est ressortie 3/3 fois en Critical.

**Score qui chute fort (40 → 15) après la correction** — pas une régression : le barème
plafonne les pénalités par palier de sévérité, et une seule issue Critical (25 points)
pèse plus lourd que tout le bruit de style Low (plafonné à 10 points). Le score à 40
avant correction était en fait trompeur, puisqu'il ne reflétait pas la présence d'une
faille d'authentification majeure.

**Déduplication imparfaite** — le filtre initial ne couvrait que les doublons Security
↔ Security (ex: LLM re-signalant une injection SQL déjà vue par Bandit). Un doublon a
échappé : "File Not Closed" (LLM) et "consider-using-with" (Pylint) sur la même ligne,
catégories différentes (Resource Management vs Code Quality). Élargi pour couvrir aussi
ce cas via les rule_id Pylint concernés (`R1732`, `W1514`).

**Catégorisation parfois forcée** — le LLM a classé un bug logique simple (pas de
vérification d'expiration de session) comme "Concurrency/Race Condition", probablement
pour rentrer dans une des catégories imposées par le schéma JSON plutôt que d'admettre
que ça relève d'autre chose. Laissé tel quel : faux positif de catégorisation mineur,
pas une vraie erreur de détection.

**Non-déterminisme du LLM** — même prompt, même fichier, résultats parfois différents
d'un run à l'autre (5 vs 6 issues LLM observées). Le renforcement du prompt réduit ce
risque pour les failles d'autorisation mais ne l'élimine pas. Avec plus de temps :
lancer plusieurs passes et agréger les résultats (majority vote), ou utiliser un modèle
plus capable sur les fichiers à enjeu de sécurité élevé, plutôt que de se fier à un seul
run.

**Pistes non explorées faute de temps** : gestion multi-fichiers/projet complet (pas
juste un fichier isolé), intégration CI/CD (commentaire automatique sur PR GitHub),
cache des résultats LLM pour éviter de repayer l'appel API sur un fichier inchangé.
