import math
from statistics import mean, pstdev


# ==============================
# UTILITÁRIOS
# ==============================

def poisson(k, lamb):
    """Probabilidade de marcar k gols dado lambda (média)."""
    return (lamb ** k) * math.exp(-lamb) / math.factorial(k)


def weighted_average(values):
    """Média ponderada (últimos jogos pesam mais)."""
    if not values:
        return 0
    n = len(values)
    weights = [i + 1 for i in range(n)]  # 1,2,3,...n (recência)
    return sum(v * w for v, w in zip(values, weights)) / sum(weights)


# ==============================
# LIGA – Fator de Força
# ==============================

LEAGUE_STRENGTH = {
    "Premier League": 1.20,
    "La Liga": 1.18,
    "Serie A": 1.15,
    "Bundesliga": 1.14,
    "Ligue 1": 1.10,
    "Championship": 1.05,
    "Primeira Liga": 1.04,
    "Jupiler Pro League": 1.03,
    "Liga Profesional Argentina": 0.88,
    "Brasileirão Série A": 1.00,
    "Brasileirão Série B": 0.92,
}


def get_league_factor(league_name: str):
    return LEAGUE_STRENGTH.get(league_name, 1.00)


# ==============================
# POISSON + AJUSTES
# ==============================

def poisson_goals_probability(avg_scored, avg_conceded, league_factor):
    """
    Calcula lambda ajustado usando ataque x defesa + força da liga.
    """
    lamb = (avg_scored * 0.55 + avg_conceded * 0.45) * league_factor
    return max(0.1, lamb)  # nunca deixar zero, evita bug


def match_under_probabilities(lamb_home, lamb_away):
    """Probabilidades agregadas de Under/Over via Poisson."""
    probs = {}

    def total_prob(max_goals):
        p = 0
        for g in range(0, max_goals + 1):
            # soma das probabilidades de cada time gerar g total
            for h in range(0, g + 1):
                a = g - h
                p += poisson(h, lamb_home) * poisson(a, lamb_away)
        return p

    probs["under_05"] = total_prob(0)
    probs["under_15"] = total_prob(1)
    probs["under_25"] = total_prob(2)
    probs["under_35"] = total_prob(3)
    probs["under_45"] = total_prob(4)

    return probs


def handicap_safety(home_lambda, away_lambda, line=3):
    """
    Calcula a probabilidade do visitante NÃO perder por mais de X gols.
    Ex: handicap +3 → probabilidade de perder por <= 2 gols.
    """
    p = 0
    for h in range(0, 10):
        for a in range(0, 10):
            if (h - a) <= line:
                p += poisson(h, home_lambda) * poisson(a, away_lambda)
    return p


# ==============================
# FORMA RECENTE + VARIÂNCIA
# ==============================

def recent_form_stats(goals_for, goals_against):
    """Calcula forma recente com pesos e variância (consistência)."""
    if not goals_for or not goals_against:
        return {
            "attack_form": 0,
            "defense_form": 0,
            "attack_var": 99,
            "defense_var": 99,
        }

    attack_form = weighted_average(goals_for)
    defense_form = weighted_average(goals_against)

    attack_var = pstdev(goals_for) if len(goals_for) > 1 else 0
    defense_var = pstdev(goals_against) if len(goals_against) > 1 else 0

    return {
        "attack_form": attack_form,
        "defense_form": defense_form,
        "attack_var": attack_var,
        "defense_var": defense_var,
    }


# ==============================
# CLASSIFICAÇÃO FINAL DA PARTIDA
# ==============================

def analyze_match(team_home, team_away, league_name):
    """
    Entrada:
      team_home = {"avg_scored": X, "avg_conceded": Y, "recent_for": [...], "recent_against": [...]}
      team_away = idem
    """
    league_factor = get_league_factor(league_name)

    # ========================
    # 1) Forma recente
    # ========================
    home_form = recent_form_stats(team_home["recent_for"], team_home["recent_against"])
    away_form = recent_form_stats(team_away["recent_for"], team_away["recent_against"])

    # ========================
    # 2) Lambda ajustado Poisson
    # ========================
    home_lambda = poisson_goals_probability(
        team_home["avg_scored"],
        team_away["avg_conceded"],
        league_factor
    )

    away_lambda = poisson_goals_probability(
        team_away["avg_scored"],
        team_home["avg_conceded"],
        league_factor
    )

    # ========================
    # 3) Under probabilities
    # ========================
    under_probs = match_under_probabilities(home_lambda, away_lambda)

    # ========================
    # 4) Handicap probabilities
    # ========================
    hcp3 = handicap_safety(home_lambda, away_lambda, 3)
    hcp4 = handicap_safety(home_lambda, away_lambda, 4)

    # ========================
    # 5) Risco do jogo (variância)
    # ========================
    variance_factor = (
        home_form["attack_var"] +
        home_form["defense_var"] +
        away_form["attack_var"] +
        away_form["defense_var"]
    ) / 4

    risk_score = max(0, min(1, 1 - (variance_factor / 3)))

    # ========================
    # 6) Score de segurança
    # ========================
    safe_score = (
        under_probs["under_35"] * 0.45 +
        under_probs["under_45"] * 0.35 +
        hcp3 * 0.20
    )

    return {
        "league_factor": league_factor,
        "home_lambda": home_lambda,
        "away_lambda": away_lambda,
        "under": under_probs,
        "handicap": {
            "+3": hcp3,
            "+4": hcp4
        },
        "risk_score": risk_score,
        "safe_score": safe_score,
        "home_form": home_form,
        "away_form": away_form,
    }
