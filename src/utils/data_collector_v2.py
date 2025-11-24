import requests
import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Importa seu modelo Fixture
from src.db import Fixture, Base, SessionLocal

load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = os.getenv("BASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

HEADERS = {
    "x-apisports-key": API_KEY
}

# Criar engine e sessão do banco
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# =====================================================
# Funções da API
# =====================================================

def api_get(url, params=None):
    """Handler seguro da API, com retry."""
    for i in range(3):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
            else:
                print(f"Erro API ({r.status_code}): {r.text}")
        except Exception as e:
            print("Erro request:", e)
        time.sleep(1)
    return None


def get_team_last_matches(team_id: int, limit: int = 5):
    """Retorna últimos jogos do time (máximo 5 no plano free)."""
    url = f"{BASE_URL}/fixtures"
    params = {
        "team": team_id,
        "last": limit
    }
    data = api_get(url, params)
    if not data:
        return []

    return data.get("response", [])


def calculate_stats_from_last_matches(matches, team_id):
    """Retorna:
    - avg_scored
    - avg_conceded
    - recent_for (lista)
    - recent_against (lista)
    """
    gols_for = []
    gols_against = []

    for m in matches:
        home = m["teams"]["home"]["id"]
        away = m["teams"]["away"]["id"]

        g_home = m["goals"]["home"] if m["goals"]["home"] is not None else 0
        g_away = m["goals"]["away"] if m["goals"]["away"] is not None else 0

        if team_id == home:
            gols_for.append(g_home)
            gols_against.append(g_away)
        else:
            gols_for.append(g_away)
            gols_against.append(g_home)

    if len(gols_for) == 0:
        return 0, 0, [], []

    avg_scored = sum(gols_for) / len(gols_for)
    avg_conceded = sum(gols_against) / len(gols_against)

    return (
        round(avg_scored, 3),
        round(avg_conceded, 3),
        gols_for[-5:],          # Últimos (máximo) 5 jogos
        gols_against[-5:]
    )


def get_fixtures_by_date(date_str):
    url = f"{BASE_URL}/fixtures"
    params = {
        "date": date_str,
        "timezone": "America/Sao_Paulo"
    }
    data = api_get(url, params)
    if not data:
        return []

    return data.get("response", [])


# =====================================================
# PROCESSAR E SALVAR FIXTURE
# =====================================================

def save_fixture(session: Session, f):
    """Cria ou atualiza fixture no banco, com todas as novas colunas."""
    fix_id = f["fixture"]["id"]
    league = f["league"]["name"]

    home_id = f["teams"]["home"]["id"]
    away_id = f["teams"]["away"]["id"]

    date_str = f["fixture"]["date"]
    dt = datetime.fromisoformat(date_str.replace("Z", ""))

    # Buscar últimos jogos e calcular stats
    home_last = get_team_last_matches(home_id)
    away_last = get_team_last_matches(away_id)

    home_avg_s, home_avg_c, home_for, home_against = calculate_stats_from_last_matches(home_last, home_id)
    away_avg_s, away_avg_c, away_for, away_against = calculate_stats_from_last_matches(away_last, away_id)

    print(f"[Fixture {fix_id}] {league} | Stats calculadas.")

    # Verificar se já existe
    db_fix = session.query(Fixture).filter(Fixture.id == fix_id).first()

    if not db_fix:
        db_fix = Fixture(id=fix_id)
        session.add(db_fix)

    # Atualizar campos
    db_fix.league_name = league
    db_fix.date = dt

    db_fix.home_id = home_id
    db_fix.away_id = away_id

    db_fix.home_avg_scored = home_avg_s
    db_fix.home_avg_conceded = home_avg_c
    db_fix.home_recent_for = home_for
    db_fix.home_recent_against = home_against

    db_fix.away_avg_scored = away_avg_s
    db_fix.away_avg_conceded = away_avg_c
    db_fix.away_recent_for = away_for
    db_fix.away_recent_against = away_against

    session.commit()


# =====================================================
# EXECUTAR COLETA DIÁRIA
# =====================================================

def collect(days_back=1, days_forward=1):
    """
    Coleta fixtures entre:
    hoje - days_back  … até hoje + days_forward
    """
    session = SessionLocal()

    today = datetime.now().date()

    for delta in range(-days_back, days_forward + 1):
        d = today + timedelta(days=delta)
        d_str = d.strftime("%Y-%m-%d")
        print(f"--- Coletando data {d_str} ---")

        fixtures = get_fixtures_by_date(d_str)
        if not fixtures:
            print("Nenhum jogo encontrado.")
            continue

        for f in fixtures:
            try:
                save_fixture(session, f)
                time.sleep(1)  # evitar limite da API
            except Exception as e:
                print("[ERRO]", e)

    session.close()


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    print("=== EPC-IA Collect v2 ===")
    collect(days_back=2, days_forward=2)
