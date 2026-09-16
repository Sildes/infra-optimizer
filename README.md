# infra-optimizer

Pipeline d'analyse et d'optimisation d'infrastructure — test technique Devoteam.

Lit un fichier de logs JSON (télémétrie serveur), détecte les anomalies, et produit
un rapport JSON structuré avec recommandations d'actions concrètes.

## Approche en une phrase

Pipeline déterministe à 4 nœuds : les anomalies sont détectées par du code testable
(seuils calibrés sur la distribution réelle des données), le LLM — optionnel — ne
rédige que les recommandations ; le rapport est générable sans clé API, de façon
strictement reproductible.

```
rapport.json -> [ingestion] -> [analyse] -> [détection] -> [recommandation] -> output.json
                  validation     agrégats     seuils +        templates (+ LLM
                  + tri          insights     fenêtres        optionnel de rédaction)
```

## Utilisation

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m infra_optimizer --input rapport.json --output output.json
```

Le mode LLM (rédaction des recommandations) s'active seul si `LLM_API_KEY` est
définie. Le client est OpenAI-compatible par HTTP : `LLM_BASE_URL` (défaut
`https://api.openai.com/v1`) et `LLM_MODEL` permettent de brancher n'importe quel
fournisseur — Mistral, GLM (Z.AI), Ollama local... — sans changer une ligne de
code, et sans dépendance SDK : un simple appel HTTP, timeout 15 s. Sans clé, ou
en cas d'échec de l'appel, le pipeline utilise les templates déterministes.
`--no-llm` force le mode déterministe.

Exemple avec GLM :

```bash
export LLM_API_KEY=...            # jamais dans le dépôt
export LLM_BASE_URL=https://api.z.ai/api/paas/v4
export LLM_MODEL=glm-4.7
```

## Décisions et arbitrages

### Pourquoi pas LangChain / LangGraph

L'énoncé cite langgraph en exemple. Mon pipeline est un graphe linéaire à 4
étapes aux contrats typés (pydantic) : pas de branchements conditionnels, pas de
boucle agentique, pas d'état partagé complexe. Un framework d'orchestration
n'apporterait ici que de la complexité. Chaque nœud étant une fonction pure, le
jour où le besoin devient un vrai graphe (retries, parallélisme, boucle), les
nœuds se branchent dans LangGraph sans réécriture.

### Où est le LLM, et où il n'est pas

- Il n'est PAS dans la détection : un seuil décide, pas une génération
  probabiliste. La détection est reproductible et testable unitairement.
- Il est dans le nœud recommandation, en option : un seul appel HTTP, le modèle
  reçoit le résumé des anomalies déjà détectées et rédige des actions claires.
  Garde-fous : sortie validée par le schéma pydantic, ids imposés (le modèle ne
  peut pas inventer de recommandation), paramètres mesurés préservés (il ne
  peut pas altérer les chiffres), repli silencieux sur les templates en cas
  d'échec. Un rapport d'infrastructure doit pouvoir être généré en CI, sans
  réseau ni dépendance à une API tierce.

### Calibration des seuils (thresholds.py)

Les seuils ne sont pas sortis du chapeau — ils sont calés sur la distribution
mesurée du jeu de données (500 échantillons, 30 min de pas, 10 jours) :

| métrique | baseline observée | pics observés | seuil retenu |
|---|---|---|---|
| cpu_usage | 52–63 % | 90–99 % | 85 % (high >= 90) |
| latency_ms | 113–142 ms | 315–384 ms | 300 ms |
| error_rate | 0.02 | 0.11–0.13 | 0.08 |
| temperature | 57–63 °C | 84–89 °C | 80 °C |
| memory / disk / io_wait | <= 68 / 63 / 4 | 84–92 / 87–97 / 10–14 | 85 / 85 / 10 |

La séparation étant franche, ces seuils ne produisent aucun faux positif sur
cette série. Limite assumée : sur une machine dont la charge nominale serait
autre (CPU de croisière à 80 %), des seuils fixes dérivent — la détection
statistique adaptative (MAD : écart à la médiane) est l'évolution naturelle,
voir « Limites ».

### Les ambiguïtés de l'énoncé, tranchées

- `timestamp` des données : contraint ISO 8601 UTC stricte (suffixe `Z`) en
  entrée ET en sortie — même contrat partout, et le tri chronologique sur ces
  chaînes est prouvé correct (tri lexicographique = tri chronologique), pas
  supposé. Un timestamp hors format est un record invalide : exclu et journalisé.
- `timestamp` du rapport : dernier record analysé (le rapport décrit l'état au
  moment de sa génération).
- `insights.error_rate` : moyenne de la période, pas la médiane — la médiane
  (0.02, la baseline) masquerait l'impact des ~83 échantillons déviants ; le
  rapport doit refléter la dégradation réelle de la période.
- `insights.uptime_seconds` : dernière valeur. Uptime est un compteur cumulatif
  (comme un kilométrage) : la moyenne n'a pas de sens physique, seule la
  dernière valeur décrit un état réel.
- `service_status_summary` : union historique des états observés (un service
  ayant été online puis offline figure dans les deux listes) — c'est un bilan
  de période, pas un instantané.
- Anomalies de service, champ `threshold` : un état n'a pas de seuil numérique
  naturel ; la règle est « au moins 1 échantillon non-online déclenche
  l'anomalie », encodée dans threshold = 1.
- Records invalides : exclus et journalisés à l'ingestion (résilience), le
  pipeline continue sur les données saines.

### Le piège des données : corrélation fallacieuse

Dans le jeu fourni, `database offline` survient 59 fois, toutes à charge
NORMALE (CPU 57–63 %, latence 113–137 ms) — aucun lien avec les pics de charge.
À l'inverse, 49 pics CPU surviennent toutes les ~5 h, systématiquement
accompagnés d'`api_gateway` dégradé : pattern récurrent de type scheduling.

La détection reste donc PAR métrique, sans corrélation automatique entre
charge et statut. La recommandation base de données parle d'investiguer la
stabilité du service (maintenance, timeouts) — jamais de « scaler la base »,
ce qui serait la conclusion fausse que les données semblent inviter à tirer.

### Agrégation temporelle des événements

Un service dégradé pendant 6 échantillons consécutifs produit UNE anomalie
(avec fenêtre début/fin et CPU moyen), pas 6. La fenêtre se prolonge tant que
deux échantillons consécutifs sont espacés d'au plus 31 minutes (pas
d'échantillonnage mesuré : 30 min sur les 499 écarts, +1 min de marge).
Au-delà — trou de collecte — la fenêtre est fermée : on ne présume jamais de
la continuité d'un état non observé ; un incident vu à travers un trou ressort
comme deux événements, par choix explicite. C'est ce que font les systèmes
d'alerting sérieux — la valeur de l'anomalie est le nombre d'échantillons
agrégés.

## Tests

Vérifications mécaniques par nœud (dataset réel + données synthétiques
corrompues), zéro dépendance réseau : ingestion (500/500, résilience, rejet
des timestamps hors format), analysis (valeurs attendues recalculées
indépendamment), detection (comptages attendus : 49 pics, 59 interruptions
base, fenêtres agrégées, sévérités, format des descriptions), et le fallback
LLM (avec clé mais appel défaillant = templates identiques). Le mode LLM
n'est pas testé en réseau par design : il n'est qu'une reformulation validée
par schéma des recommandations déterministes, elles intégralement testées.

## Limites et évolutions

- Seuils fixes calés sur ce jeu : passer à une détection adaptative (MAD /
  écart-type robuste à la médiane) si la baseline cible varie.
- Corrélation multi-métriques : les pics CPU+latence+erreur simultanés sont un
  seul phénomène sous-jacent ; une agrégation cross-métrique réduirait le
  nombre d'anomalies redondantes au prix d'une complexité d'interprétation.
- Mode watch : réanalyse incrémentale à chaque nouvel échantillon.
- Export HTML du rapport pour lecture humaine.

## Structure

```
src/infra_optimizer/
  models.py        # contrats d'entrée/sortie (pydantic) — aucune logique
  thresholds.py    # toute la politique de détection, documentée
  pipeline.py      # orchestration + CLI
  __main__.py      # point d'entrée : python -m infra_optimizer
  llm.py           # client LLM HTTP OpenAI-compatible (optionnel, garde-fous)
  nodes/
    ingestion.py       # lecture, validation, tri chronologique
    analysis.py        # agrégats -> insights
    detection.py       # anomalies par seuils + fenêtres de service
    recommendation.py  # templates déterministes + enrichissement LLM
```
