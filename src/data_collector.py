# src/data_collector.py
import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta
from db import SessionLocal, create_tables, League, Team, Fixture, Standing
from sqlalchemy.exc import IntegrityError

load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = os.getenv("BASE_URL", "https://v3.football.api-sports.io")
HEADERS = {"x-apisports-key": API_KEY}

# Ligas grandes permitidas (somente estas serão coletadas)
LIGAS_PERMITIDAS = [
    39,   # Premier League
    140,  # La Liga
    135,  # Serie A
    61,   # Ligue 1
    78,   # Bundesliga
    40,   # Championship
    94,   # Primeira Liga (Portugal)
    144,  # Jupiler Pro League
    128,  # Liga Argentina
    71,   # Brasileirão A
    72    # Brasileirão B
]

session = SessionLocal()

# util: upsert league
def upsert_league(league_obj):
    api_id = league_obj["id"]
    name = league_obj.get("name")
    country = league_obj.get("country")
    league = session.query(League).filter_by(api_id=api_id).first()
    if not league:
        league = League(api_id=api_id, name=name, country=country)
        session.add(league)
        session.commit()
        session.refresh(league)
    return league

def upsert_team(team_obj):
    api_id = team_obj["id"]
    name = team_obj.get("name")
    country = team_obj.get("country", {}).get("name") if isinstance(team_obj.get("country"), dict) else None
    team = session.query(Team).filter_by(api_id=api_id).first()
    if not team:
        team = Team(api_id=api_id, name=name, country=country)
        session.add(team)
        session.commit()
        session.refresh(team)
    return team

def save_fixture_from_api(fx):
    api_id = fx["fixture"]["id"]
    date_str = fx["fixture"]["date"]
    date = datetime.fromisoformat(date_str.replace("Z","+00:00"))
    league_info = fx["league"]
    league = upsert_league(league_info)
    home = upsert_team(fx["teams"]["home"])
    away = upsert_team(fx["teams"]["away"])

    fixture = session.query(Fixture).filter_by(api_id=api_id).first()
    status = fx["fixture"]["status"].get("short") if fx["fixture"].get("status") else None
    home_goals = fx["goals"].get("home") if fx.get("goals") else None
    away_goals = fx["goals"].get("away") if fx.get("goals") else None

    if not fixture:
        fixture = Fixture(
            api_id=api_id,
            league_id=league.id,
            date=date,
            home_team_id=home.id,
            away_team_id=away.id,
            status=status,
            home_goals=home_goals,
            away_goals=away_goals
        )
        session.add(fixture)
    else:
        fixture.league_id = league.id
        fixture.date = date
        fixture.home_team_id = home.id
        fixture.away_team_id = away.id
        fixture.status = status
        fixture.home_goals = home_goals
        fixture.away_goals = away_goals
    try:
        session.commit()
    except IntegrityError:
        session.rollback()

def fetch_fixtures_date(date_str):
    url = f"{BASE_URL}/fixtures?date={date_str}&timezone=America/Sao_Paulo"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        print("Erro API fixtures:", r.status_code, r.text[:200])
        return []
    data = r.json()
    return data.get("response", [])

def fetch_standings(league_id, season):
    url = f"{BASE_URL}/standings?league={league_id}&season={season}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        print("Erro API standings:", r.status_code, r.text[:200])
        return []
    return r.json().get("response", [])

# def collect_for_date(date_obj):
#     date_str = date_obj.strftime("%Y-%m-%d")
#     print("Coletando fixtures para", date_str)
#     fixtures = fetch_fixtures_date(date_str)
#     for fx in fixtures:
#         save_fixture_from_api(fx)

def collect_for_date(date_obj):
    date_str = date_obj.strftime("%Y-%m-%d")
    print("Coletando fixtures para", date_str)

    fixtures = fetch_fixtures_date(date_str)

    for fx in fixtures:

        league_id = fx["league"]["id"]

        # SE A LIGA NÃO ESTÁ ENTRE AS PERMITIDAS → IGNORA
        if league_id not in LIGAS_PERMITIDAS:
            continue

        # Agora só salva ligas fortes
        save_fixture_from_api(fx)

def collect_range(days_back=7, days_forward=1):
    # coleta de dias atrás (histórico) e dias futuros (próximos jogos)
    today = datetime.now()
    for d in range(days_back, 0, -1):
        dt = today - timedelta(days=d)
        collect_for_date(dt)
    collect_for_date(today)
    for d in range(1, days_forward+1):
        dt = today + timedelta(days=d)
        collect_for_date(dt)

if __name__ == "__main__":
    create_tables()
    # coleta inicial: 30 dias no passado e 2 dias à frente (ajuste conforme quiser)
    collect_range(days_back=30, days_forward=2)
    print("Coleta inicial concluída.")
