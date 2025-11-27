# src/core/generator.py
"""
Gerador de bilhetes (versão melhorada mantendo compatibilidade).
Principais pontos:
- Usa stats_engine.analyze_match quando disponível para melhorar estimativas.
- Mantém interface: generate_markets(fixture), find_ticket_for_target(...), compute_risk_score(...)
- Busca combinações até 4 seleções para atingir target_odd entre [target_odd, target_odd + tol]
"""
from datetime import datetime, timedelta
from math import exp
from sqlalchemy.orm import joinedload
from src.db import SessionLocal, Fixture, Team
import itertools
import math
import traceback

# Tentativa de usar analyze_match do stats_engine (melhor)
try:
    from src.core.stats_engine import analyze_match
except Exception:
    analyze_match = None

# -----------------------
# Helpers básicos / Poisson
# -----------------------
def poisson(lmbd, k):
    # segurança: lmbd > 0
    lmbd = max(0.01, float(lmbd))
    return (lmbd ** k) * math.exp(-lmbd) / math.factorial(k)

def prob_total_goals_under(exp_home, exp_away, limit):
    total = exp_home + exp_away
    p = 0.0
    for g in range(0, limit + 1):
        p += poisson(total, g)
    return min(max(p, 0.0), 1.0)

# -----------------------
# Fallback: estatísticas locais (se stats_engine não estiver disponível)
# -----------------------
def quick_team_stats(team_id):
    """
    Fallback simples para quando analyze_match não estiver disponível.
    Usa fixtures salvos no banco (sem exigir que sejam FT).
    """
    db = SessionLocal()
    fixtures = db.query(Fixture).filter(
        ((Fixture.home_team_id == team_id) | (Fixture.away_team_id == team_id))
    ).order_by(Fixture.date.desc()).limit(10).all()
    db.close()

    if not fixtures:
        return {"games":0,"avg_scored":0.9,"avg_conceded":1.0,"p_under_35":0.7,"p_under_45":0.9,"p_over_05":0.9}

    scored = 0
    conceded = 0
    total = 0
    under35 = 0
    under45 = 0
    over05 = 0
    for m in fixtures:
        if m.home_goals is None or m.away_goals is None:
            continue
        if m.home_team_id == team_id:
            s = m.home_goals
            c = m.away_goals
        else:
            s = m.away_goals
            c = m.home_goals
        scored += s
        conceded += c
        total += 1
        tot = (m.home_goals or 0) + (m.away_goals or 0)
        if tot <= 3:
            under35 += 1
        if tot <= 4:
            under45 += 1
        if tot >= 1:
            over05 += 1

    if total == 0:
        return {"games":0,"avg_scored":0.9,"avg_conceded":1.0,"p_under_35":0.7,"p_under_45":0.9,"p_over_05":0.9}

    return {
        "games": total,
        "avg_scored": scored / total,
        "avg_conceded": conceded / total,
        "p_under_35": under35 / total,
        "p_under_45": under45 / total,
        "p_over_05": over05 / total
    }

# -----------------------
# Geração de mercados para um fixture
# -----------------------
def generate_markets(fixture):
    """
    Gera lista de mercados seguros para o fixture.
    Cada mercado: {fixture, market, prob, odd, explain}
    """
    markets = []
    try:
        # preferir analyze_match se disponível (usa stats_engine.py). :contentReference[oaicite:3]{index=3}
        if analyze_match:
            info = analyze_match(fixture.home_team_id, fixture.away_team_id, matches_limit=10)
        else:
            info = None
    except Exception:
        info = None
        traceback.print_exc()

    # se analyze_match disponível, usamos suas probabilidades
    if info:
        p_u35 = info.get("p_under_35", 0.75)
        p_u45 = info.get("p_under_45", 0.92)
        exp_total = info.get("expected_total", 2.2)
        # away goals expectation approximada
        exp_away = info.get("expected_away", exp_total / 2)
    else:
        # fallback rápido: estimativas a partir do banco
        home_s = quick_team_stats(fixture.home_team_id)
        away_s = quick_team_stats(fixture.away_team_id)
        exp_home = max(0.1, (home_s["avg_scored"] + away_s["avg_conceded"]) / 2)
        exp_away = max(0.1, (away_s["avg_scored"] + home_s["avg_conceded"]) / 2)
        exp_total = exp_home + exp_away
        p_u35 = prob_total_goals_under(exp_home, exp_away, 3)
        p_u45 = prob_total_goals_under(exp_home, exp_away, 4)

    # derived probabilities
    p_under_35 = float(p_u35)
    p_under_45 = float(p_u45)
    # prob away <=2 based on Poisson with exp_away
    p_away_le2 = sum(poisson(exp_away, k) for k in range(0, 3))
    p_over_05 = 1.0 - prob_total_goals_under(exp_total, 0, 0)  # conservative

    # Helper to compute an offered odd with small margin and sane bounds
    def offered_odd(prob, margin_factor=1.02, min_odd=1.01, max_odd=1.12):
        if prob <= 0:
            return max_odd
        odd = (1.0 / prob) * margin_factor
        odd = max(min_odd, min(max_odd, round(odd, 3)))
        return odd

    # Build markets (ordered by safety)
    markets.append({
        "fixture": fixture,
        "market": "Under 3.5",
        "prob": round(p_under_35, 4),
        "odd": offered_odd(p_under_35, margin_factor=1.03, max_odd=1.08),
        "explain": f"Total estimado de gols ≈ {round(exp_total,2)} → alta chance de ≤3 gols."
    })

    markets.append({
        "fixture": fixture,
        "market": "Under 4.5",
        "prob": round(p_under_45, 4),
        "odd": offered_odd(p_under_45, margin_factor=1.02, max_odd=1.05),
        "explain": "Mercado amplo e conservador (≤4 gols)."
    })

    markets.append({
        "fixture": fixture,
        "market": "Away Under 2.5",
        "prob": round(p_away_le2, 4),
        "odd": offered_odd(p_away_le2, margin_factor=1.03, max_odd=1.09),
        "explain": f"{fixture.away_team.name} tem baixa média de gols (segurança para Under 2.5)."
    })

    # Handicap +2/+3 (proteção para empate/derrota larga) — usamos p_under_45 como base
    markets.append({
        "fixture": fixture,
        "market": "Handicap +3 (away)",
        "prob": min(0.995, max(0.6, p_under_45)),  # muito seguro se under45 alto
        "odd": offered_odd(min(0.995, max(0.6, p_under_45)), margin_factor=1.01, max_odd=1.03),
        "explain": "Handicap +3 — proteção extra baseada no total estimado de gols."
    })

    # Optional: Over 0.5 when confidence is extremely high for at least one side scoring
    if p_over_05 > 0.95:
        markets.append({
            "fixture": fixture,
            "market": "Over 0.5",
            "prob": round(p_over_05, 4),
            "odd": offered_odd(p_over_05, margin_factor=1.02, max_odd=1.03),
            "explain": "Alta probabilidade de pelo menos 1 gol no jogo."
        })

    # Sort markets by decreasing prob (mais seguros primeiro)
    markets.sort(key=lambda x: x["prob"], reverse=True)
    return markets

# -----------------------
# Risk / confidence helpers
# -----------------------
def compute_risk_score(selections):
    """
    Retorna um score de risco [0..1], onde 0 = altíssima segurança, 1 = alto risco.
    - Usa a probabilidade combinada (produto das probs)
    - Ajusta por número de seleções (mais seleções = maior risco)
    """
    if not selections:
        return 1.0
    probs = [max(1e-6, float(s.get("prob", 0.01))) for s in selections]
    combined = 1.0
    for p in probs:
        combined *= p
    # Ajuste conservador: penaliza conjuntos longos
    n = len(probs)
    # transforma combined prob em "confiança" e então converte para risco
    conf = combined ** (1.0 / max(1, n))  # média geométrica
    risk = 1.0 - conf
    # Normalizar e clamp
    return max(0.0, min(1.0, round(risk, 4)))

def explain_ticket(selections):
    """Gera lista de explicações legíveis para um ticket."""
    out = []
    for s in selections:
        f = s["fixture"]
        out.append(f"{f.home_team.name} x {f.away_team.name} — {s['market']} — Prob: {round(s['prob']*100,1)}% — {s.get('explain')}")
    return out

# -----------------------
# Construção do bilhete (procura combinações <= 4 seleções)
# -----------------------
def _find_combination(candidates, target_odd, max_selections=4, tol=0.02, top_n=30):
    """
    Tenta encontrar uma combinação de 1..max_selections entre candidatos com odd final
    entre [target_odd, target_odd + tol]. Retorna a melhor combinação (mais segura).
    - candidates: lista de mercados (ordenados por prob desc)
    - top_n: limitar número de candidatos considerados para evitar explosion
    """
    # filtra candidatos válidos e limita
    valid = [c for c in candidates if c.get("prob", 0.0) > 0.02 and c.get("odd", 1.0) >= 1.01]
    valid = valid[:top_n]

    if not valid:
        return None

    best = None
    best_conf = -1.0  # queremos máxima confiança (produto das probs)
    target_low = target_odd
    target_high = target_odd + tol

    # verificar combinações por tamanho (tenta 1..max_selections)
    for r in range(1, max_selections + 1):
        # geração de combinações (podemos adaptar para heurísticas)
        for combo in itertools.combinations(valid, r):
            # evitar duas seleções do mesmo fixture
            fixtures = {c["fixture"].id for c in combo}
            if len(fixtures) < len(combo):
                continue
            # calcular odd final
            final_odd = 1.0
            for c in combo:
                final_odd *= float(c.get("odd", 1.0))
            if final_odd < target_low or final_odd > target_high:
                continue
            # calcular confiança: produto das probs (maior = melhor)
            prod_prob = 1.0
            for c in combo:
                prod_prob *= float(c.get("prob", 0.0))
            # preferir mais alta confiança; se empate, escolher menor final_odd
            if prod_prob > best_conf or (abs(prod_prob - best_conf) < 1e-12 and final_odd < best.get("final_odd", 999)):
                best_conf = prod_prob
                best = {
                    "selections": list(combo),
                    "final_odd": round(final_odd, 3),
                    "combined_prob": round(prod_prob, 6)
                }
        # se encontramos alguma combinação no tamanho r, podemos preferir retornar a melhor encontrada já
        if best:
            return best
    return None

def find_ticket_for_target(days=2, target_odd=1.15, mode=1, max_selections=4):
    """
    Interface pública esperada pelo server.py:
    - days: procurar jogos entre hoje e hoje+days
    - target_odd: alvo final (ex.: 1.15)
    - mode: reservado (por enquanto não usado; no futuro pode controlar conservadorismo)
    """
    db = SessionLocal()
    today = datetime.now()
    end = today + timedelta(days=days)
    fixtures = (
        db.query(Fixture)
        .options(joinedload(Fixture.home_team), joinedload(Fixture.away_team))
        .filter(Fixture.date >= today, Fixture.date <= end)
        .all()
    )
    db.close()

    # coletar candidatos de mercados
    candidates = []
    for f in fixtures:
        try:
            mkts = generate_markets(f)
            # anotar fixture ref para serialização posterior
            for m in mkts:
                candidates.append(m)
        except Exception:
            traceback.print_exc()
            continue

    if not candidates:
        return None

    # ordenar por prob desc
    candidates.sort(key=lambda x: x.get("prob", 0.0), reverse=True)

    # tentar combinações (busca controlada)
    combo = _find_combination(candidates, target_odd, max_selections=max_selections, tol=0.05, top_n=30)
    if not combo:
        # fallback greedy: adicionar mercados mais seguros até alcançar target (máx max_selections)
        ticket_sel = []
        final_odd = 1.0
        for c in candidates:
            # mínimo prob razoável
            if c.get("prob", 0) < 0.03:
                continue
            if any(s["fixture"].id == c["fixture"].id for s in ticket_sel):
                continue
            ticket_sel.append(c)
            final_odd *= c.get("odd", 1.0)
            if final_odd >= target_odd or len(ticket_sel) >= max_selections:
                break
        if not ticket_sel:
            return None
        combo = {
            "selections": ticket_sel,
            "final_odd": round(final_odd, 3),
            "combined_prob": round(math.prod([s.get("prob", 0.0) for s in ticket_sel]), 6)
        }

    # build ticket structure
    selections = combo["selections"]
    final_odd = combo["final_odd"]
    combined_prob = combo["combined_prob"]
    # compute risk and recommendation
    sel_list = []
    
    
    for s in selections:
        fix = s["fixture"]
        
        # --- aplicar tradução de mercado ---
        market_display = format_market_name({
            "market": s["market"],
            "home": fix.home_team.name,
            "away": fix.away_team.name
        })
        
        sel_list.append({
            "fixture_id": fix.id,
            "home": fix.home_team.name if fix.home_team else None,
            "away": fix.away_team.name if fix.away_team else None,
            "date": fix.date.isoformat() if fix.date else None,
            "market": market_display,
            "prob": s["prob"],
            "odd": s["odd"],
            "explain": s.get("explain")
        })

    risk_score = compute_risk_score(selections)
    if risk_score <= 0.20:
        rec = "Alta segurança"
    elif risk_score <= 0.45:
        rec = "Moderada"
    else:
        rec = "Requer revisão"

    explanation = explain_ticket(selections)

    ticket = {
        "target_odd": target_odd,
        "final_odd": float(final_odd),
        "selections": sel_list,
        "combined_prob": round(float(combined_prob), 6),
        "confidence_formatted": f"{round(float(combined_prob)*100,1)}%",
        "risk_score": risk_score,
        "system_recommendation": rec,
        "explanation": explanation,
        "mode": mode
    }
    return ticket

def format_market_name(sel):
    market = sel["market"]
    home = sel["home"]
    away = sel["away"]

    # 1) HOME UNDER
    if market.startswith("Home Under"):
        total = market.replace("Home Under ", "")
        return f"{home} — Menos de {total} gols"

    # 2) AWAY UNDER
    if market.startswith("Away Under"):
        total = market.replace("Away Under ", "")
        return f"{away} — Menos de {total} gols"

    # 3) UNDER GLOBAL
    if market.startswith("Under"):
        total = market.replace("Under ", "")
        return f"Menos de {total} gols no jogo"

    # 4) OVER GLOBAL
    if market.startswith("Over"):
        total = market.replace("Over ", "")
        return f"Mais de {total} gols no jogo"

    # fallback caso não encontre
    return market
