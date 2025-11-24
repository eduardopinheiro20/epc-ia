from sqlalchemy import func
from src.db import SessionLocal, Fixture
from math import exp, factorial

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
