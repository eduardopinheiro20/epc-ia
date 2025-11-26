import requests
import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

# MODELOS REAIS DO BANCO
from src.db import (
    SessionLocal,
    League,
    Team,
    Fixture,
    create_tables,
)

load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = os.getenv("BASE_URL")
HEADERS = {"x-apisports-key": API_KEY}

# LIGAS GRANDES
LIGAS_PERMITIDAS = [
    39,   # Premier League
    140,  # La Liga
    135,  # Serie A
    61,   # Ligue 1
    78,   # Bundesliga
    40,   # Championship
    94,   # Primeira Liga
    144,  # Jupiler Pro League
    128,  # Liga Argentina
    71,   # Brasileirão A
    72,   # Brasileirão B
    
    #    Competições UEFA
    2,    # Champions League
    3,    # Europa League
    848   # Conference League
]

session = SessionLocal()


# ============================================================
# API GET SEGURO
# ============================================================

def api_get(url, params=None):
    for _ in range(3):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
            print("API ERROR:", r.status_code, r.text[:200])
        except Exception as e:
            print("Erro request:", e)
        time.sleep(1)
    return None


# ============================================================
# UPSERT LEAGUE E TEAM (IGUAL AO v1)
# ============================================================

def upsert_league(api_league):
    api_id = api_league["id"]
    name = api_league.get("name")
    country = api_league.get("country")

    league = session.query(League).filter_by(api_id=api_id).first()
    if league:
        return league

    league = League(api_id=api_id, name=name, country=country)
    session.add(league)
    session.commit()
    session.refresh(league)
    return league


def upsert_team(api_team):
    api_id = api_team["id"]
    name = api_team.get("name")
    country = api_team.get("country", None)

    team = session.query(Team).filter_by(api_id=api_id).first()
    if team:
        return team

    team = Team(api_id=api_id, name=name, country=country)
    session.add(team)
    session.commit()
    session.refresh(team)
    return team


# ============================================================
# ESTATÍSTICAS (V2)
# ============================================================

def get_last_matches(team_id, limit=5):
    url = f"{BASE_URL}/fixtures"
    params = {"team": team_id, "last": limit}

    data = api_get(url, params)
    if not data:
        return []

    return data.get("response", [])


def compute_stats(matches, team_id):
    gols_for = []
    gols_against = []

    for m in matches:
        if "goals" not in m:
            continue

        home_id = m["teams"]["home"]["id"]
        g_home = m["goals"]["home"] or 0
        g_away = m["goals"]["away"] or 0

        if home_id == team_id:
            gols_for.append(g_home)
            gols_against.append(g_away)
        else:
            gols_for.append(g_away)
            gols_against.append(g_home)

    if not gols_for:
        return 0, 0, [], []

    avg_scored = round(sum(gols_for) / len(gols_for), 3)
    avg_conceded = round(sum(gols_against) / len(gols_against), 3)

    return avg_scored, avg_conceded, gols_for, gols_against


# ============================================================
# SALVAR FIXTURE (COM TUDO: IGUAL v1 + v2)
# ============================================================

def save_fixture(fx):

    if "fixture" not in fx or not fx["fixture"].get("id"):
        print("[IGNORADO] fixture inválido")
        return

    if "league" not in fx:
        print("[IGNORADO] sem liga")
        return

    league_api = fx["league"]
    league_id = league_api["id"]

    if league_id not in LIGAS_PERMITIDAS:
        print("[IGNORADO] liga não permitida:", league_api.get("name"))
        return

    # -----------------------------------
    # CAMPOS BÁSICOS DO FIXTURE
    # -----------------------------------
    api_id = fx["fixture"]["id"]
    date = datetime.fromisoformat(fx["fixture"]["date"].replace("Z", "+00:00"))
    status = fx["fixture"]["status"].get("short")

    # -----------------------------------
    # GOLS → FALTAVA NO V2
    # -----------------------------------
    home_goals = fx["goals"]["home"] if fx.get("goals") else None
    away_goals = fx["goals"]["away"] if fx.get("goals") else None

    # -----------------------------------
    # UPSERT LEAGUE e TEAM
    # -----------------------------------
    league = upsert_league(league_api)
    home_team = upsert_team(fx["teams"]["home"])
    away_team = upsert_team(fx["teams"]["away"])

    # -----------------------------------
    # ESTATÍSTICAS DOS ÚLTIMOS JOGOS
    # -----------------------------------
    home_last = get_last_matches(home_team.api_id)
    away_last = get_last_matches(away_team.api_id)

    (
        home_avg_s,
        home_avg_c,
        home_recent_for,
        home_recent_against
    ) = compute_stats(home_last, home_team.api_id)

    (
        away_avg_s,
        away_avg_c,
        away_recent_for,
        away_recent_against
    ) = compute_stats(away_last, away_team.api_id)

    print(f"[Fixture {api_id}] {league_api['name']} | Stats (OK)")

    # -----------------------------------
    # SALVAR NO BANCO
    # -----------------------------------
    fix = session.query(Fixture).filter_by(api_id=api_id).first()
    if not fix:
        fix = Fixture(api_id=api_id)
        session.add(fix)

    fix.league_id = league.id
    fix.date = date
    fix.status = status

    fix.home_team_id = home_team.id
    fix.away_team_id = away_team.id

    fix.home_goals = home_goals
    fix.away_goals = away_goals

    fix.home_avg_scored = home_avg_s
    fix.home_avg_conceded = home_avg_c
    fix.home_recent_for = home_recent_for
    fix.home_recent_against = home_recent_against

    fix.away_avg_scored = away_avg_s
    fix.away_avg_conceded = away_avg_c
    fix.away_recent_for = away_recent_for
    fix.away_recent_against = away_recent_against

    try:
        session.commit()
    except Exception as e:
        session.rollback()
        print("[ERRO] ao salvar fixture:", e)


# ============================================================
# LOOP DE COLETA
# ============================================================

def collect(days_back=2, days_forward=2):
    today = datetime.now().date()

    for delta in range(-days_back, days_forward + 1):
        d = today + timedelta(days=delta)
        d_str = d.strftime("%Y-%m-%d")
        print(f"\n--- Coletando {d_str} ---")

        url = f"{BASE_URL}/fixtures"
        params = {"date": d_str, "timezone": "America/Sao_Paulo"}

        data = api_get(url, params)
        if not data:
            print("Nenhum jogo encontrado.")
            continue

        for fx in data.get("response", []):
            save_fixture(fx)
            time.sleep(0.6)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    create_tables()
    print("=== EPC-IA Collect v2 ===")
    collect(days_back=2, days_forward=2)
