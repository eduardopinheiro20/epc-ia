# caminho: src/core/generator.py
# (cole/replace o conteúdo atual pelo abaixo ou aplique as mudanças equivalentes)

from math import exp, factorial
from datetime import datetime, timedelta
from src.db import SessionLocal, Fixture, Team
from sqlalchemy.orm import joinedload
import math

# --- poisson ---
def poisson(lmbd, k):
    return (lmbd ** k) * math.exp(-lmbd) / math.factorial(k)

# --- busca histórico (usa fixtures do banco) ---
def get_team_history(team_id):
    db = SessionLocal()
    fixtures = db.query(Fixture).filter(
        ((Fixture.home_team_id == team_id) | (Fixture.away_team_id == team_id))
    ).order_by(Fixture.date.desc()).all()
    db.close()
    return fixtures

def team_stats(team_id):
    games = get_team_history(team_id)
    if not games:
        # retorna pseudo-estatística conservadora quando não há histórico
        return {
            "games": 0,
            "avg_scored": 0.9,
            "avg_conceded": 1.0,
            "gf_list": [],
            "ga_list": [],
            "freq_3plus": 0,
            "freq_suffer_3plus": 0
        }

    gf, ga = [], []
    for g in games:
        if g.home_team_id == team_id:
            gf.append(g.home_goals or 0)
            ga.append(g.away_goals or 0)
        else:
            gf.append(g.away_goals or 0)
            ga.append(g.home_goals or 0)

    total = len(gf)
    return {
        "games": total,
        "avg_scored": sum(gf) / total if total else 0.9,
        "avg_conceded": sum(ga) / total if total else 1.0,
        "gf_list": gf,
        "ga_list": ga,
        "freq_3plus": sum(1 for x in gf if x >= 3),
        "freq_suffer_3plus": sum(1 for x in ga if x >= 3)
    }

def calc_probabilities(home_stats, away_stats):
    Lh = max(0.1, (home_stats["avg_scored"] + away_stats["avg_conceded"]) / 2)
    La = max(0.1, (away_stats["avg_scored"] + home_stats["avg_conceded"]) / 2)

    # p under 3.5
    p_u35 = 0.0
    for total_gols in range(0, 4):  # 0..3
        for h in range(0, total_gols + 1):
            a = total_gols - h
            p_u35 += poisson(Lh, h) * poisson(La, a)

    # p under 4.5
    p_u45 = 0.0
    for total_gols in range(0, 5):  # 0..4
        for h in range(0, total_gols + 1):
            a = total_gols - h
            p_u45 += poisson(Lh, h) * poisson(La, a)

    # away <=2 goals
    p_away_le2 = sum(poisson(La, k) for k in range(0, 3))

    return {
        "Lh": Lh,
        "La": La,
        "p_under_35": round(p_u35, 4),
        "p_under_45": round(p_u45, 4),
        "p_away_le2": round(p_away_le2, 4)
    }

def generate_markets(fixture):
    home_id = fixture.home_team_id
    away_id = fixture.away_team_id

    home_s = team_stats(home_id)
    away_s = team_stats(away_id)

    probs = calc_probabilities(home_s, away_s)

    markets = []
    markets.append({
        "fixture": fixture,
        "market": "Under 3.5",
        "prob": probs["p_under_35"],
        "odd": round(1.0 / max(0.01, probs["p_under_35"]) * 1.03, 3),
        "explain": f"{fixture.home_team.name} e {fixture.away_team.name} têm tendência por jogos com poucos gols."
    })
    markets.append({
        "fixture": fixture,
        "market": "Under 4.5",
        "prob": probs["p_under_45"],
        "odd": round(1.0 / max(0.01, probs["p_under_45"]) * 1.02, 3),
        "explain": "Under 4.5 - mercado seguro quando baixa produção ofensiva."
    })
    markets.append({
        "fixture": fixture,
        "market": "Away Under 2.5",
        "prob": probs["p_away_le2"],
        "odd": round(1.0 / max(0.01, probs["p_away_le2"]) * 1.03, 3),
        "explain": f"{fixture.away_team.name} raramente marca 3+ gols."
    })
    # handicap +3
    markets.append({
        "fixture": fixture,
        "market": "Handicap +3 (away)",
        "prob": min(0.995, probs["p_under_45"]),
        "odd": round(1.0 / max(0.01, min(0.995, probs["p_under_45"])) * 1.01, 3),
        "explain": "Handicap +3 - proteção extra baseada no total estimado de gols."
    })

    markets.sort(key=lambda x: x["prob"], reverse=True)
    return markets

# small helper: compute risk score
def compute_risk_score(selections):
    # risk: quanto menor a prob combinada, maior o risco
    if not selections:
        return 1.0
    probs = [s["prob"] for s in selections]
    combined = 1.0
    for p in probs:
        combined *= p
    # conservative adjust:
    risk = 1.0 - combined ** (1 / max(1, len(probs)))
    # clamp
    return max(0.0, min(1.0, round(risk, 4)))

# gerar ticket
def find_ticket_for_target(days=2, target_odd=1.15, mode=1):
    db = SessionLocal()
    today = datetime.now()
    end = today + timedelta(days=days)
    fixtures = (
        db.query(Fixture)
        .options(
            joinedload(Fixture.home_team),
            joinedload(Fixture.away_team)
        )
        .filter(Fixture.date >= today, Fixture.date <= end)
        .all()
    )
    db.close()

    candidates = []
    for f in fixtures:
        mkts = generate_markets(f)
        for m in mkts:
            candidates.append(m)

    if not candidates:
        return None

    # montar bilhete priorizando mercados mais seguros (maior prob)
    candidates.sort(key=lambda x: x["prob"], reverse=True)

    ticket_sel = []
    final_odd = 1.0
    for c in candidates:
        # prefer markets with decent odds and prob > 0.05
        if c["prob"] < 0.05:
            continue
        # evitar duas seleções do mesmo fixture
        if any(s["fixture"].id == c["fixture"].id for s in ticket_sel):
            continue
        ticket_sel.append(c)
        final_odd *= c["odd"]
        if final_odd >= target_odd:
            break

    if not ticket_sel:
        return None

    # build ticket object with fields requested
    combined_prob = min(s["prob"] for s in ticket_sel)  # conservative per selection
    risk_score = compute_risk_score(ticket_sel)
    # human recommendation
    if risk_score <= 0.20:
        rec = "Alta segurança"
    elif risk_score <= 0.45:
        rec = "Moderada"
    else:
        rec = "Requer revisão"

    # convert selections to serializable structure
    selections_serial = []
    explanations = []
    for s in ticket_sel:
        fix = s["fixture"]
        selections_serial.append({
            "fixture_id": fix.id,
            "home": fix.home_team.name,
            "away": fix.away_team.name,
            "date": fix.date.isoformat(),
            "market": s["market"],
            "prob": s["prob"],
            "odd": s.get("odd"),
            "explain": s.get("explain")
        })
        explanations.append(f"{fix.home_team.name} x {fix.away_team.name} — {s['market']}: {round(s['prob']*100,1)}% — {s.get('explain')}")

    ticket = {
        "target_odd": target_odd,
        "final_odd": round(final_odd, 3),
        "selections": selections_serial,
        "combined_prob": round(combined_prob, 4),
        "confidence_formatted": f"{round(combined_prob*100,1)}%",
        "risk_score": risk_score,
        "system_recommendation": rec,
        "explanation": explanations,
        # convenience for UI
        "jogo": {
            "home": ticket_sel[0]["fixture"].home_team.name,
            "away": ticket_sel[0]["fixture"].away_team.name,
            "date": ticket_sel[0]["fixture"].date.isoformat(),
            "home_logo": None,
            "away_logo": None
        },
        "market": ticket_sel[0]["market"],
        "odd": ticket_sel[0].get("odd"),
        "confidence": round(ticket_sel[0]["prob"], 4)
    }

    return ticket

def explain_ticket(ticket):
    # mantém compatibilidade: string list
    out = []
    for s in ticket.get("explanation", []):
        out.append(s)
    return out

# compatibility wrapper if some code expects candidate_markets_for_fixture
def candidate_markets_for_fixture(fixture):
    return generate_markets(fixture)
