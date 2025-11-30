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
    79,   # Bundesliga 2 
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

def api_get_fixture_statistics(fixture_api_id):
    """Busca estatísticas do fixture na API-Football (se disponível no plano free)."""
    url = f"{BASE_URL}/fixtures/statistics"
    params = {"fixture": fixture_api_id}
    data = api_get(url, params)
    if not data:
        return None
    return data.get("response", [])


# ============================================================
# MatchStatistics
# ============================================================
def upsert_match_statistics(db, fixture_id, team_db_id, stats):
    """Cria ou atualiza entrada em MatchStatistics para o time e fixture."""
    from src.db import MatchStatistics  # importar aqui para evitar ciclos

    record = (
        db.query(MatchStatistics)
        .filter_by(fixture_id=fixture_id, team_id=team_db_id)
        .first()
    )

    if not record:
        record = MatchStatistics(
            fixture_id=fixture_id,
            team_id=team_db_id
        )
        db.add(record)

    # Setar todas as propriedades, somente se existir no dict
    for key, value in stats.items():
        setattr(record, key, value)

    db.commit()
    db.refresh(record)

    return record


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
        
        # -----------------------------------
        # TENTAR BUSCAR ESTATÍSTICAS DA PARTIDA NA API (FREE)
        # -----------------------------------
        stats_api = None
        if status not in ["NS", "TBD"]:  # só busca quando a partida começou ou terminou
            stats_api = api_get_fixture_statistics(api_id)

        # inicializar tudo como None (seguro para partidas futuras)
        home_shots_total = away_shots_total = None
        home_shots_on_target = away_shots_on_target = None
        home_corners = away_corners = None
        home_yellow = away_yellow = None
        home_red = away_red = None
        home_possession = away_possession = None
        home_pass_accuracy = away_pass_accuracy = None
        home_assists = away_assists = None

        if stats_api:
            # API retorna 2 entradas: [ {team:home, stats:[...]}, {team:away,...} ]
            for item in stats_api:
                team_id = item["team"]["id"]
                entries = item["statistics"]

                # helper convert
                def val(key):
                    for s in entries:
                        if s["type"].lower() == key.lower():
                            v = s["value"]
                            if isinstance(v, str) and "%" in v:
                                try:
                                    return float(v.replace("%", ""))
                                except:
                                    return None
                            return v
                    return None

                # HOME
                if team_id == fx["teams"]["home"]["id"]:
                    home_shots_total = val("Total Shots")
                    home_shots_on_target = val("Shots on Goal")
                    home_corners = val("Corner Kicks")
                    home_yellow = val("Yellow Cards")
                    home_red = val("Red Cards")
                    home_possession = val("Ball Possession")
                    home_pass_accuracy = val("Passes %")
                    home_assists = val("Assists")

                # AWAY
                if team_id == fx["teams"]["away"]["id"]:
                    away_shots_total = val("Total Shots")
                    away_shots_on_target = val("Shots on Goal")
                    away_corners = val("Corner Kicks")
                    away_yellow = val("Yellow Cards")
                    away_red = val("Red Cards")
                    away_possession = val("Ball Possession")
                    away_pass_accuracy = val("Passes %")
                    away_assists = val("Assists")

        # SALVAR NO FIXTURE
        fix.home_shots_total = home_shots_total
        fix.away_shots_total = away_shots_total

        fix.home_shots_on_target = home_shots_on_target
        fix.away_shots_on_target = away_shots_on_target

        fix.home_corners = home_corners
        fix.away_corners = away_corners

        fix.home_yellow = home_yellow
        fix.away_yellow = away_yellow

        fix.home_red = home_red
        fix.away_red = away_red

        fix.home_possession = home_possession
        fix.away_possession = away_possession

        fix.home_pass_accuracy = home_pass_accuracy
        fix.away_pass_accuracy = away_pass_accuracy

        fix.home_assists = home_assists
        fix.away_assists = away_assists
        
        
        
        # -----------------------------------
        # ESTATÍSTICAS DO FIXTURE (FREE API)
        # -----------------------------------
        stats_api = None
        if status not in ["NS", "TBD"]:
            stats_api = api_get_fixture_statistics(api_id)

        # valores default
        home_stats = {}
        away_stats = {}

        # stats usadas no Fixture
        fix_stats_home = {}
        fix_stats_away = {}

        if stats_api:
            for item in stats_api:
                team_api_id = item["team"]["id"]
                entries = item["statistics"]

                def val(key):
                    for s in entries:
                        if s["type"].lower() == key.lower():
                            v = s["value"]
                            if v is None:
                                return None
                            if isinstance(v, str) and "%" in v:
                                try:
                                    return float(v.replace("%",""))
                                except:
                                    return None
                            return v
                    return None

                mapped = {
                    "shots_total": val("Total Shots"),
                    "shots_on_goal": val("Shots on Goal"),
                    "shots_off_goal": val("Shots off Goal"),
                    "blocked_shots": val("Blocked Shots"),
                    "shots_inside_box": val("Shots insidebox"),
                    "shots_outside_box": val("Shots outsidebox"),
                    "possession": val("Ball Possession"),
                    "corners": val("Corner Kicks"),
                    "fouls": val("Fouls"),
                    "yellow_cards": val("Yellow Cards"),
                    "red_cards": val("Red Cards"),
                    "saves": val("Goalkeeper Saves"),
                    "total_passes": val("Total passes"),
                    "accurate_passes": val("Passes accurate"),
                    "pass_accuracy": val("Passes %"),
                    "expected_goals": val("Expected Goals"),
                    "dangerous_attacks": val("Dangerous Attacks"),
                    "assists": val("Assists"),
                }

                # HOME
                if team_api_id == fx["teams"]["home"]["id"]:
                    home_stats = mapped

                    # preencher Fixture
                    fix_stats_home = {
                        "home_shots_total": mapped["shots_total"],
                        "home_shots_on_target": mapped["shots_on_goal"],
                        "home_corners": mapped["corners"],
                        "home_yellow": mapped["yellow_cards"],
                        "home_red": mapped["red_cards"],
                        "home_possession": mapped["possession"],
                        "home_pass_accuracy": mapped["pass_accuracy"],
                        "home_assists": mapped["assists"],
                    }

                # AWAY
                if team_api_id == fx["teams"]["away"]["id"]:
                    away_stats = mapped

                    fix_stats_away = {
                        "away_shots_total": mapped["shots_total"],
                        "away_shots_on_target": mapped["shots_on_goal"],
                        "away_corners": mapped["corners"],
                        "away_yellow": mapped["yellow_cards"],
                        "away_red": mapped["red_cards"],
                        "away_possession": mapped["possession"],
                        "away_pass_accuracy": mapped["pass_accuracy"],
                        "away_assists": mapped["assists"],
                    }

        # Atualizar Fixture com as stats
        for k, v in fix_stats_home.items():
            setattr(fix, k, v)

        for k, v in fix_stats_away.items():
            setattr(fix, k, v)

        # -----------------------------------
        # SALVAR MatchStatistics (HOME & AWAY)
        # -----------------------------------

        if home_stats:
            upsert_match_statistics(
                db=db,
                fixture_id=fix.id,
                team_db_id=home_team.id,
                stats={
                    "shots_total": home_stats["shots_total"],
                    "shots_on_goal": home_stats["shots_on_goal"],
                    "shots_off_goal": home_stats["shots_off_goal"],
                    "blocked_shots": home_stats["blocked_shots"],
                    "shots_inside_box": home_stats["shots_inside_box"],
                    "shots_outside_box": home_stats["shots_outside_box"],
                    "possession": home_stats["possession"],
                    "corners": home_stats["corners"],
                    "fouls": home_stats["fouls"],
                    "yellow_cards": home_stats["yellow_cards"],
                    "red_cards": home_stats["red_cards"],
                    "saves": home_stats["saves"],
                    "total_passes": home_stats["total_passes"],
                    "accurate_passes": home_stats["accurate_passes"],
                    "pass_accuracy": home_stats["pass_accuracy"],
                    "expected_goals": home_stats["expected_goals"],
                    "dangerous_attacks": home_stats["dangerous_attacks"],
                },
            )

        if away_stats:
            upsert_match_statistics(
                db=db,
                fixture_id=fix.id,
                team_db_id=away_team.id,
                stats={
                    "shots_total": away_stats["shots_total"],
                    "shots_on_goal": away_stats["shots_on_goal"],
                    "shots_off_goal": away_stats["shots_off_goal"],
                    "blocked_shots": away_stats["blocked_shots"],
                    "shots_inside_box": away_stats["shots_inside_box"],
                    "shots_outside_box": away_stats["shots_outside_box"],
                    "possession": away_stats["possession"],
                    "corners": away_stats["corners"],
                    "fouls": away_stats["fouls"],
                    "yellow_cards": away_stats["yellow_cards"],
                    "red_cards": away_stats["red_cards"],
                    "saves": away_stats["saves"],
                    "total_passes": away_stats["total_passes"],
                    "accurate_passes": away_stats["accurate_passes"],
                    "pass_accuracy": away_stats["pass_accuracy"],
                    "expected_goals": away_stats["expected_goals"],
                    "dangerous_attacks": away_stats["dangerous_attacks"],
                },
            )

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
