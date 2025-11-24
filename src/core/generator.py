from datetime import datetime, timedelta
from typing import Dict, Any, List
import math

from src.db import SessionLocal, Fixture
from src.core.stats_engine import analyze_match

# --------------------------------------------
# CONVERTE PROBABILIDADE EM ODD (com margem)
# --------------------------------------------
def implied_odd(prob: float, margin: float = 0.03):
    if prob <= 0:
        return 50.0
    fair = 1 / prob
    return round(fair * (1 + margin), 3)


# --------------------------------------------
# COMBINAÇÃO DE ODDS
# --------------------------------------------
def combine_odds(odds: List[float]):
    o = 1.0
    for x in odds:
        o *= x
    return round(o, 3)


# --------------------------------------------
# MARKETS (Under, HT, Handicap, etc.)
# --------------------------------------------
def candidate_markets_for_fixture(fixture: Fixture) -> List[Dict[str, Any]]:
    a = analyze_match(fixture.home_team_id, fixture.away_team_id)

    if not a:
        return []

    markets = []

    # Under 3.5
    prob = a["p_under_35"]
    markets.append({
        "fixture_id": fixture.id,
        "market": "Under 3.5",
        "prob": prob,
        "odd": implied_odd(prob),
        "explain": "Probabilidade baseada no modelo Poisson + médias ofensivas/defensivas."
    })

    # Under 4.5
    prob = a["p_under_45"]
    markets.append({
        "fixture_id": fixture.id,
        "market": "Under 4.5",
        "prob": prob,
        "odd": implied_odd(prob),
        "explain": "Mercado extremamente seguro com base na soma esperada de gols."
    })

    # HT Under 1.5
    prob = a["p_under_ht_15"]
    markets.append({
        "fixture_id": fixture.id,
        "market": "HT Under 1.5",
        "prob": prob,
        "odd": implied_odd(prob),
        "explain": "Primeiro tempo com tendência forte de baixa produção ofensiva."
    })

    # Handicap +3 (away)
    prob = min(0.98, a["p_under_45"])  # heurística básica
    markets.append({
        "fixture_id": fixture.id,
        "market": "Handicap +3 (away)",
        "prob": prob,
        "odd": implied_odd(prob),
        "explain": "Handicap estatístico gerado por baixa diferença esperada de gols."
    })

    # Handicap +4
    prob = min(0.995, a["p_under_45"])
    markets.append({
        "fixture_id": fixture.id,
        "market": "Handicap +4 (away)",
        "prob": prob,
        "odd": implied_odd(prob),
        "explain": "Handicap ultra seguro baseado no limite extremo."
    })

    return markets


# --------------------------------------------
# GERA APENAS O MELHOR TICKET DO DIA
# --------------------------------------------
def generate_ticket(fixtures: List[Fixture], target_odd=1.15, mode=1):
    candidates = []

    for f in fixtures:
        mkts = candidate_markets_for_fixture(f)
        for m in mkts:
            score = m["prob"]  # score simples
            m["score"] = score
            candidates.append(m)

    if mode == 1:  # conservador
        candidates = [c for c in candidates if c["prob"] >= 0.75]
    elif mode == 2:  # balanceado
        candidates = [c for c in candidates if c["prob"] >= 0.60]

    candidates.sort(key=lambda x: x["score"], reverse=True)

    ticket = []
    current_odds = 1.0
    used = set()

    for c in candidates:
        if c["fixture_id"] in used:
            continue

        new_odd = current_odds * c["odd"]
        ticket.append(c)
        used.add(c["fixture_id"])
        current_odds = new_odd

        if current_odds >= target_odd:
            break

    return {
        "target_odd": target_odd,
        "final_odd": round(current_odds, 3),
        "confidence": round(sum(t["prob"] for t in ticket) / len(ticket), 3),
        "selections": ticket,
    }


# --------------------------------------------
# MULTI-DAY TICKET SELECTION
# --------------------------------------------
def find_ticket_for_target(days=1, mode=1, target_odd=1.30):
    session = SessionLocal()
    today = datetime.utcnow().date()
    end = today + timedelta(days=days - 1)

    fixtures = (
        session.query(Fixture)
        .filter(Fixture.date >= today, Fixture.date <= end)
        .all()
    )
    session.close()

    if not fixtures:
        return None

    return generate_ticket(fixtures, target_odd=target_odd, mode=mode)


# --------------------------------------------
# EXPLICAÇÃO
# --------------------------------------------
def explain_ticket(ticket):
    msg = []
    msg.append(f"O bilhete busca odd {ticket['target_odd']}.")
    msg.append(f"Odd final: {ticket['final_odd']}.")
    msg.append(f"Confiança média: {ticket['confidence']}.")
    msg.append("Seleções:")

    for s in ticket["selections"]:
        msg.append(f"- {s['market']} | prob={s['prob']} | odd={s['odd']}")

    return "\n".join(msg)
