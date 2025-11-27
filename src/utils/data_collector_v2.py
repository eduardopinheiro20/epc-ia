# src/utils/data_collector_v2.py
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
    Standing,
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

    # Competições UEFA
    2,    # Champions League
    3,    # Europa League
    848   # Conference League
]

# NOTA: usaremos conexões locais (SessionLocal()) dentro de funções para evitar sessions globais
# session = SessionLocal()  # removi uso global para segurança

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

def upsert_league(api_league, db):
    api_id = api_league["id"]
    name = api_league.get("name")
    country = api_league.get("country")

    league = db.query(League).filter_by(api_id=api_id).first()
    if league:
        return league

    league = League(api_id=api_id, name=name, country=country)
    db.add(league)
    db.commit()
    db.refresh(league)
    return league


def upsert_team(api_team, db):
    api_id = api_team["id"]
    name = api_team.get("name")
    country = api_team.get("country", None)

    team = db.query(Team).filter_by(api_id=api_id).first()
    if team:
        return team

    team = Team(api_id=api_id, name=name, country=country)
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


# ============================================================
# ESTATÍSTICAS (V2) — agora com fallback para DB
# ============================================================

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


def api_get_last_matches(team_api_id, limit=10):
    """
    Tenta buscar últimos jogos pela API (quando disponível).
    """
    url = f"{BASE_URL}/fixtures"
    params = {"team": team_api_id, "last": limit}
    data = api_get(url, params)
    if not data:
        return []
    return data.get("response", [])


def db_get_last_matches(team_db_id, limit=10):
    """
    Busca últimos jogos FT do time no banco (usaremos quando a API não tiver dados).
    Retorna estrutura simples compatível com compute_stats (mas com chave 'goals' e 'teams').
    """
    db = SessionLocal()
    try:
        fixtures = (
            db.query(Fixture)
            .filter(
                ((Fixture.home_team_id == team_db_id) | (Fixture.away_team_id == team_db_id)),
                Fixture.status == "FT"
            )
            .order_by(Fixture.date.desc())
            .limit(limit)
            .all()
        )

        out = []
        for f in fixtures:
            # precisamos das ids da API dos times (Team.api_id)
            home_team = db.query(Team).filter(Team.id == f.home_team_id).first()
            away_team = db.query(Team).filter(Team.id == f.away_team_id).first()
            if not home_team or not away_team:
                continue

            out.append({
                "teams": {
                    "home": {"id": home_team.api_id},
                    "away": {"id": away_team.api_id}
                },
                "goals": {
                    "home": f.home_goals if f.home_goals is not None else 0,
                    "away": f.away_goals if f.away_goals is not None else 0
                }
            })

        return out
    finally:
        db.close()


# ============================================================
# Helpers para atualizar fixtures relacionados a um time
# ============================================================

def update_team_stats_on_fixtures(team_db_id, avg_s, avg_c, recent_for, recent_against):
    """
    Atualiza fixtures (todos) envolvendo esse time — para que fixtures futuros recém-inseridos
    já tenham as estatísticas preenchidas (home_* ou away_*).
    """
    db = SessionLocal()
    try:
        fixtures = db.query(Fixture).filter(
            (Fixture.home_team_id == team_db_id) | (Fixture.away_team_id == team_db_id)
        ).all()

        for f in fixtures:
            if f.home_team_id == team_db_id:
                f.home_avg_scored = avg_s
                f.home_avg_conceded = avg_c
                f.home_recent_for = recent_for
                f.home_recent_against = recent_against
            if f.away_team_id == team_db_id:
                f.away_avg_scored = avg_s
                f.away_avg_conceded = avg_c
                f.away_recent_for = recent_for
                f.away_recent_against = recent_against
        db.commit()
    except Exception as e:
        db.rollback()
        print("[ERRO] update_team_stats_on_fixtures:", e)
    finally:
        db.close()


# ============================================================
# SALVAR FIXTURE (COM TUDO: IGUAL v1 + v2) — atualizado
# ============================================================

def save_fixture(fx):
    """
    Salva/atualiza fixture + tenta preencher estatísticas:
     - tenta usar API para últimos jogos
     - se API não devolver, usa dados FT do banco
     - atualiza fixtures existentes envolvendo os times com as estatísticas calculadas
    """
    if "fixture" not in fx or not fx["fixture"].get("id"):
        print("[IGNORADO] fixture inválido")
        return

    if "league" not in fx:
        print("[IGNORADO] sem liga")
        return

    league_api = fx["league"]
    league_id = league_api["id"]

    if league_id not in LIGAS_PERMITIDAS:
        # print para debug
        print("[IGNORADO] liga não permitida:", league_api.get("name"))
        return

    # -----------------------------------
    # CAMPOS BÁSICOS DO FIXTURE
    # -----------------------------------
    api_id = fx["fixture"]["id"]
    date = datetime.fromisoformat(fx["fixture"]["date"].replace("Z", "+00:00"))
    status = fx["fixture"]["status"].get("short")

    # -----------------------------------
    # GOLS → PODE SER None
    # -----------------------------------
    home_goals = fx["goals"]["home"] if fx.get("goals") else None
    away_goals = fx["goals"]["away"] if fx.get("goals") else None

    db = SessionLocal()
    try:
        # UPSERT LEAGUE e TEAM
        league = upsert_league(league_api, db)
        home_team = upsert_team(fx["teams"]["home"], db)
        away_team = upsert_team(fx["teams"]["away"], db)

        # -----------------------------------
        # TENTAR BUSCAR ÚLTIMOS JOGOS PELA API
        # -----------------------------------
        home_last_api = api_get_last_matches(home_team.api_id, limit=10)
        away_last_api = api_get_last_matches(away_team.api_id, limit=10)

        # se api não retornou (ou vazio) usamos db fallback
        if not home_last_api:
            home_last_api = db_get_last_matches(home_team.id, limit=10)
        if not away_last_api:
            away_last_api = db_get_last_matches(away_team.id, limit=10)

        (
            home_avg_s,
            home_avg_c,
            home_recent_for,
            home_recent_against
        ) = compute_stats(home_last_api, home_team.api_id if home_last_api and len(home_last_api)>0 else home_team.api_id)

        (
            away_avg_s,
            away_avg_c,
            away_recent_for,
            away_recent_against
        ) = compute_stats(away_last_api, away_team.api_id if away_last_api and len(away_last_api)>0 else away_team.api_id)

        print(f"[Fixture {api_id}] {league_api['name']} | Stats (OK)")

        # SALVAR/UPSERT fixture
        fix = db.query(Fixture).filter_by(api_id=api_id).first()
        if not fix:
            fix = Fixture(api_id=api_id)
            db.add(fix)

        fix.league_id = league.id
        fix.date = date
        fix.status = status

        fix.home_team_id = home_team.id
        fix.away_team_id = away_team.id

        fix.home_goals = home_goals
        fix.away_goals = away_goals

        # preencher estatísticas (mesmo que fixture ainda não seja FT)
        fix.home_avg_scored = home_avg_s
        fix.home_avg_conceded = home_avg_c
        fix.home_recent_for = home_recent_for
        fix.home_recent_against = home_recent_against

        fix.away_avg_scored = away_avg_s
        fix.away_avg_conceded = away_avg_c
        fix.away_recent_for = away_recent_for
        fix.away_recent_against = away_recent_against

        db.commit()

        # ------------------------------------------------
        # Atualiza fixtures relacionados para que todos tenham estatísticas consistentes
        # (isso preenche fixtures futuros já na base)
        # ------------------------------------------------
        update_team_stats_on_fixtures(home_team.id, home_avg_s, home_avg_c, home_recent_for, home_recent_against)
        update_team_stats_on_fixtures(away_team.id, away_avg_s, away_avg_c, away_recent_for, away_recent_against)

    except Exception as e:
        db.rollback()
        print("[ERRO] ao salvar fixture:", e)
    finally:
        db.close()


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
# REPROCESSAR ESTATÍSTICAS (USANDO APENAS SEU BANCO)
# ============================================================

def reprocessar_estatisticas(limit=10):
    print("\n=== Reprocessando estatísticas internas ===")

    db = SessionLocal()

    try:
        # pegar todos times do banco
        teams = db.query(Team).all()

        for team in teams:
            # buscar últimos fixtures FT do time
            fixtures = (
                db.query(Fixture)
                .filter(
                    ((Fixture.home_team_id == team.id) | (Fixture.away_team_id == team.id)),
                    Fixture.status == "FT"
                )
                .order_by(Fixture.date.desc())
                .limit(limit)
                .all()
            )

            if not fixtures:
                continue

            gols_for = []
            gols_against = []

            for f in fixtures:
                if f.home_goals is None or f.away_goals is None:
                    continue

                if f.home_team_id == team.id:
                    gols_for.append(f.home_goals)
                    gols_against.append(f.away_goals)
                else:
                    gols_for.append(f.away_goals)
                    gols_against.append(f.home_goals)

            if not gols_for:
                continue

            avg_s = round(sum(gols_for) / len(gols_for), 3)
            avg_c = round(sum(gols_against) / len(gols_against), 3)

            recent_for = gols_for[:5]
            recent_against = gols_against[:5]

            # atualizar todos fixtures envolvendo esse time
            # (aqui atualizamos apenas os fixtures retornados; update_team_stats_on_fixtures atualiza todos)
            for f in fixtures:
                if f.home_team_id == team.id:
                    f.home_avg_scored = avg_s
                    f.home_avg_conceded = avg_c
                    f.home_recent_for = recent_for
                    f.home_recent_against = recent_against
                else:
                    f.away_avg_scored = avg_s
                    f.away_avg_conceded = avg_c
                    f.away_recent_for = recent_for
                    f.away_recent_against = recent_against

            # também propagar para todos fixtures (opcional, garante consistência)
            update_team_stats_on_fixtures(team.id, avg_s, avg_c, recent_for, recent_against)

        db.commit()
        print("Estatísticas reprocessadas com sucesso!")
    except Exception as e:
        db.rollback()
        print("[ERRO] Reprocessar estatísticas:", e)
    finally:
        db.close()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    create_tables()
    print("=== EPC-IA Collect v2 ===")
    # coleta fixtures
    collect(days_back=2, days_forward=2)
    # reprocessa estatísticas após coleta
    reprocessar_estatisticas(limit=10)
