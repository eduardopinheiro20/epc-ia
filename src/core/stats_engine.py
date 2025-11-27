from requests import Session
from sqlalchemy import func
from src.db import SessionLocal, Fixture
from math import exp, factorial
from datetime import datetime, timedelta

session = SessionLocal()

# --------------------------------------------
# Busca últimos jogos finalizados
# --------------------------------------------
def get_last_matches(team_id, limit=10):
    return (
        session.query(Fixture)
        .filter(
            ((Fixture.home_team_id == team_id) | (Fixture.away_team_id == team_id)),
            Fixture.status == "FT"
        )
        .order_by(Fixture.date.desc())
        .limit(limit)
        .all()
    )

# --------------------------------------------
# Estatísticas básicas do time
# --------------------------------------------
def compute_stats(team_id, limit=10):
    matches = get_last_matches(team_id, limit)
    if not matches:
        return None

    total_scored = 0
    total_conceded = 0
    total_goals = 0
    under35 = 0
    under25 = 0
    over05 = 0

    for m in matches:
        home = m.home_goals or 0
        away = m.away_goals or 0

        if m.home_team_id == team_id:
            scored = home
            conceded = away
        else:
            scored = away
            conceded = home

        total_scored += scored
        total_conceded += conceded
        total_goals += home + away

        if home + away <= 3:
            under35 += 1
        if home + away <= 2:
            under25 += 1
        if home + away >= 1:
            over05 += 1

    games = len(matches)

    return {
        "games": games,
        "avg_scored": total_scored / games,
        "avg_conceded": total_conceded / games,
        "avg_goals": total_goals / games,
        "p_under_35": under35 / games,
        "p_under_25": under25 / games,
        "p_over_05": over05 / games,
    }

# --------------------------------------------
# Função Poisson
# --------------------------------------------
def poisson(lmbd, k):
    return (lmbd ** k) * exp(-lmbd) / factorial(k)

# --------------------------------------------
# Esperança de gols
# --------------------------------------------
def expected_goals(home_stats, away_stats):
    home_exp = (home_stats["avg_scored"] + away_stats["avg_conceded"]) / 2
    away_exp = (away_stats["avg_scored"] + home_stats["avg_conceded"]) / 2
    return max(home_exp, 0.1), max(away_exp, 0.1)

# --------------------------------------------
# Probabilidade total de gols
# --------------------------------------------
def prob_total_goals_under(exp_home, exp_away, limit):
    total_exp = exp_home + exp_away
    prob = 0
    for g in range(limit + 1):
        prob += poisson(total_exp, g)
    return prob

# --------------------------------------------
# FINAL: FUNÇÃO EXIGIDA PELO GENERATOR.PY
# --------------------------------------------
def analyze_match(home_id, away_id, matches_limit=10):
    home_stats = compute_stats(home_id, limit=matches_limit)
    away_stats = compute_stats(away_id, limit=matches_limit)

    if not home_stats or not away_stats:
        return None

    exp_home, exp_away = expected_goals(home_stats, away_stats)

    return {
        "home": home_stats,
        "away": away_stats,
        "expected_home": exp_home,
        "expected_away": exp_away,
        "expected_total": exp_home + exp_away,
        "p_under_35": prob_total_goals_under(exp_home, exp_away, 3),
        "p_under_45": prob_total_goals_under(exp_home, exp_away, 4),
        "p_under_ht_15": prob_total_goals_under(exp_home / 2, exp_away / 2, 1),
    }


# ============================================================
# FORMA RECENTE (V, E, D) E MÉDIAS EXTENDIDAS
# ============================================================

def get_extended_team_stats(db: Session, team_id: int, limit: int = 15):
    """
    Retorna estatísticas profundas do time:
    - forma V/E/D
    - força ofensiva e defensiva (médias)
    - médias móveis (5, 10, 15)
    - % under 3.5, under 4.5, over 2.5
    - volatilidade ofensiva
    """

    matches = (
        db.query(Fixture)
        .filter(
            (Fixture.home_team_id == team_id) |
            (Fixture.away_team_id == team_id),
            Fixture.status == "FT",
        )
        .order_by(Fixture.date.desc())
        .limit(limit)
        .all()
    )

    if not matches:
        return None

    # -------------------------------------
    # Estatísticas base
    # -------------------------------------
    forma = []  # ["V", "E", "D"]
    gols_for = []
    gols_against = []

    under35 = 0
    under45 = 0
    over25 = 0

    for m in matches:
        if m.home_team_id == team_id:
            gf = m.home_goals or 0
            ga = m.away_goals or 0
        else:
            gf = m.away_goals or 0
            ga = m.home_goals or 0

        # forma
        if gf > ga:
            forma.append("V")
        elif gf == ga:
            forma.append("E")
        else:
            forma.append("D")

        gols_for.append(gf)
        gols_against.append(ga)

        total = gf + ga
        if total <= 3:
            under35 += 1
        if total <= 4:
            under45 += 1
        if total >= 3:
            over25 += 1

    jogos = len(matches)

    stats = {
        "forma": forma,
        "forma_str": " ".join(forma[:6]),
        "jogos_analisados": jogos,

        # médias gerais
        "avg_scored": sum(gols_for) / jogos,
        "avg_conceded": sum(gols_against) / jogos,

        # médias móveis
        "avg5_scored": sum(gols_for[:5]) / min(5, jogos),
        "avg5_conceded": sum(gols_against[:5]) / min(5, jogos),

        "avg10_scored": sum(gols_for[:10]) / min(10, jogos),
        "avg10_conceded": sum(gols_against[:10]) / min(10, jogos),

        # volatilidade (quanto o time oscila)
        "volatilidade_ofensiva":
            (max(gols_for) - min(gols_for)) if jogos > 1 else 0,

        # frequências
        "under35_rate": under35 / jogos,
        "under45_rate": under45 / jogos,
        "over25_rate": over25 / jogos,
    }

    return stats


# ============================================================
# ESTATÍSTICAS DA LIGA
# ============================================================

def get_league_patterns(db: Session, league_id: int, limit: int = 200):
    """
    Estatísticas globais da liga:
    - média de gols
    - tendência under/over
    - volatilidade
    """
    matches = (
        db.query(Fixture)
        .filter(Fixture.league_id == league_id, Fixture.status == "FT")
        .order_by(Fixture.date.desc())
        .limit(limit)
        .all()
    )

    if not matches:
        return None

    totals = [ (m.home_goals or 0) + (m.away_goals or 0) for m in matches ]

    under35 = len([t for t in totals if t <= 3])
    under45 = len([t for t in totals if t <= 4])
    over25  = len([t for t in totals if t >= 3])

    stats = {
        "jogos": len(matches),
        "media_gols": sum(totals) / len(matches),
        "volatilidade": max(totals) - min(totals),

        "under35_rate": under35 / len(matches),
        "under45_rate": under45 / len(matches),
        "over25_rate": over25 / len(matches),
    }

    return stats


# ============================================================
# FUNÇÃO FINAL: COMBO DE ESTATÍSTICAS DO JOGO
# ============================================================

def compute_match_features(db: Session, fixture: Fixture):
    """
    Retorna um pacote completo de informações do jogo para o gerador:
    - estatísticas avançadas do time mandante
    - estatísticas avançadas do time visitante
    - padrão da liga
    - ajuste de confiança baseado nos times
    """

    home = get_extended_team_stats(db, fixture.home_team_id)
    away = get_extended_team_stats(db, fixture.away_team_id)
    league_stats = get_league_patterns(db, fixture.league_id)

    return {
        "home": home,
        "away": away,
        "league": league_stats,
    }