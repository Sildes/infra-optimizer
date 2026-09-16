"""Client LLM optionnel — enrichissement des recommandations.

Contrat (voir nodes/recommendation.py) :
- le mode déterministe est le DÉFAUT et ne dépend JAMAIS de ce module ;
- ce module n'est utilisé que si LLM_API_KEY est définie ;
- le LLM RÉDIGE, il ne décide pas : il reçoit les recommandations déjà
  calculées (avec les chiffres mesurés) et ne peut pas les inventer —
  sa sortie est revalidée par pydantic, champ parameters inchangé ;
- toute erreur (réseau, timeout, sortie invalide) remonte à l'appelant,
  qui replie silencieusement sur les templates.

OpenAI-compatible par HTTP (aucun SDK) : LLM_BASE_URL et LLM_MODEL
permettent de brancher n'importe quel fournisseur — OpenAI, Mistral,
GLM (Z.AI), Ollama local — sans changer le code.

Aucun secret dans le code : la clé vient de l'environnement (LLM_API_KEY),
jamais du dépôt.
"""
import json
import os
import urllib.request

from pydantic import BaseModel

from infra_optimizer.models import Anomaly, Recommendation

# Un seul appel, timeout généreux : le LLM est un bonus, pas une dépendance.
# 120 s mesuré nécessaire pour 10 recos via GLM (prompt résumé + reformulation) ;
# le pipeline est un batch, pas une API interactive.
_TIMEOUT_S = 120


class _Rewrite(BaseModel):
    """Sortie attendue du LLM (une entrée par recommandation, mêmes ids)."""

    id: str
    action: str
    benefit_estimate: str


def _chat(base_url: str, api_key: str, model: str, prompt: str) -> str:
    """Un appel /chat/completions OpenAI-compatible. Lève en cas d'échec."""
    requete = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            }
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(requete, timeout=_TIMEOUT_S) as reponse:
        corps = json.loads(reponse.read())
    return corps["choices"][0]["message"]["content"]


def rewrite_recommendations(
    anomalies: list[Anomaly], templates: list[Recommendation]
) -> list[Recommendation]:
    """Réécrit action/benefit_estimate des templates via le LLM.

    Lève en cas d'échec (réseau, clé invalide, sortie non conforme) :
    l'appelant (recommendation.py) replie alors sur les templates inchangés.
    """
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    api_key = os.environ["LLM_API_KEY"]

    resume = "\n".join(f"- {a.metric}: {a.description}" for a in anomalies[:50])
    corps = "\n".join(
        f'- "{r.id}": action="{r.action}" benefit="{r.benefit_estimate}"'
        for r in templates
    )

    texte = _chat(
        base_url,
        api_key,
        model,
        "Tu es consultant infrastructure. Améliore la formulation des "
        "recommandations suivantes pour un CTO. CONTRAT : tu ne changes NI les "
        "ids, NI les chiffres, NI les faits ; tu réécris seulement action et "
        "benefit_estimate (français, concret, une phrase). Réponds UNIQUEMENT "
        'en JSON : liste d\'objets {"id", "action", "benefit_estimate"}.\n\n'
        f"Anomalies détectées (extrait) :\n{resume}\n\n"
        f"Recommandations à reformuler :\n{corps}",
    )

    # Le modèle peut envelopper le JSON dans des balises markdown : on extrait
    # le premier tableau JSON valide de la réponse.
    debut, fin = texte.find("["), texte.rfind("]")
    reecrits = [_Rewrite.model_validate(t) for t in json.loads(texte[debut : fin + 1])]

    # On applique les réécritures SANS toucher aux faits (parameters, target).
    par_id = {r.id: r for r in reecrits}
    sortie: list[Recommendation] = []
    for t in templates:
        if (nouveau := par_id.get(t.id)) is not None:
            sortie.append(
                Recommendation(
                    id=t.id,
                    action=nouveau.action,
                    target=t.target,
                    parameters=t.parameters,  # chiffres mesurés : intouchables
                    benefit_estimate=nouveau.benefit_estimate,
                )
            )
        else:
            sortie.append(t)  # reco absente de la réponse LLM -> template tel quel
    return sortie
