# src/api/server.py

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
from src.db import SessionLocal, Fixture, Ticket, TicketSelection, Bankroll
from src.core.generator import find_ticket_for_target, explain_ticket
from src.core.stats_engine import compute_stats
from src.api.service import SaveTicketRequest, save_ticket_to_db  
from datetime import datetime
from sqlalchemy.orm import joinedload
import json
import hashlib

app = FastAPI(title="EPC-IA Betting AI")

# ===== CORS =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== HEALTH =====
@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now()}


# ====================================================================
#  BILHETE DO DIA — MODO NOTIFY (NÃO SALVA)
# ====================================================================
@app.get("/bilhete-do-dia")
def bilhete_do_dia(mode: int = 1, target_odd: float = 1.15, days: int = 2):
    """
    Gera bilhete do dia em modo NOTIFY.
    NÃO salva no banco.
    O front (Spring + Angular) decide se deve salvar.
    """
    ticket = find_ticket_for_target(days=days, target_odd=target_odd, mode=mode)

    if not ticket:
        return {"found": False, "msg": "Nenhuma seleção segura encontrada."}

    # IA já retorna risk_score, system_recommendation, explanation, jogo, etc.
    return {"found": True, "ticket": ticket}


# ====================================================================
#  SALVAR BILHETE — Chamado pelo SPRING QUANDO O USUÁRIO CLICA “SALVAR”
# ====================================================================

@app.post("/salvar-bilhete")
def save_ticket(data: dict):
    db = SessionLocal()

    try:
        t = data.get("ticket")
        if not t:
            raise HTTPException(status_code=400, detail="Ticket ausente.")

        selections = t.get("selections", [])
        final_odd = t.get("final_odd")
        combined_prob = t.get("combined_prob")

        # ---- CALCULA A ASSINATURA AQUI DENTRO ----
        signature_raw = json.dumps(selections, sort_keys=True) + str(final_odd)
        signature = hashlib.md5(signature_raw.encode()).hexdigest()

        # Verifica duplicata ANTES de salvar
        existing = db.query(Ticket).filter_by(signature=signature).first()
        if existing:
            return {"saved": True, "ticket_id": existing.id, "duplicate": True}

        meta = {
            "explanation": t.get("explanation"),
            "system_recommendation": t.get("system_recommendation"),
            "confidence_formatted": t.get("confidence_formatted"),
        }

        # Cria Ticket
        ticket = Ticket(
            created_by="SYSTEM",
            status="PENDING",
            final_odd=final_odd,
            combined_prob=combined_prob,
            applied_to_bankroll=False,
            bankroll_id=None,
            meta=meta,
            signature=signature
        )
        db.add(ticket)
        db.flush()  # obter ticket.id

        # Criar selections
        for s in selections:
            ts = TicketSelection(
                ticket_id=ticket.id,
                fixture_id=s["fixture_id"],
                market=s["market"],
                odd=s["odd"],
                prob=s["prob"],
                home_name=s["home"],
                away_name=s["away"]
            )
            db.add(ts)

        db.commit()

        return {"saved": True, "ticket_id": ticket.id}

    except Exception as e:
        db.rollback()
        print("Erro ao salvar ticket:", e)
        raise HTTPException(status_code=500, detail="Erro ao salvar ticket.")

    finally:
        db.close()

# ====================================================================
#  HISTÓRICO DE TICKETS 

@app.get("/historico-tickets")
def historico_tickets(
    page: int = 1,
    size: int = 20,
    start: str | None = None,
    end: str | None = None
):
    db = SessionLocal()

    try:
        query = (
            db.query(Ticket)
            .options(joinedload(Ticket.selections))
        )

        # ------------------------------
        # FILTRO POR DATA (usando saved_at)
        # ------------------------------
        if start:
            try:
                dt = datetime.fromisoformat(start)
                query = query.filter(Ticket.saved_at >= dt)
            except:
                pass

        if end:
            try:
                dt = datetime.fromisoformat(end)
                query = query.filter(Ticket.saved_at <= dt)
            except:
                pass

        total = query.count()

        tickets = (
            query.order_by(Ticket.saved_at.desc())
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )

        items = []

        for t in tickets:

            # DATA DO TICKET (conversão segura)
            saved_at = (
                t.saved_at.isoformat()
                if getattr(t, "saved_at", None)
                else None
            )

            # FINAL ODD
            final_odd = float(t.final_odd) if t.final_odd else None

            # PROBABILIDADE COMBINADA
            combined_prob = (
                float(t.combined_prob)
                if t.combined_prob is not None
                else None
            )

            # ------------------------------
            # CONSTRUIR SELEÇÕES CORRETAMENTE
            # ------------------------------
            selections = []
            for s in getattr(t, "selections", []):
                selections.append({
                    "id": s.id,
                    "fixture_id": s.fixture_id,
                    "home": s.home_name,
                    "away": s.away_name,
                    "market": s.market,
                    "odd": float(s.odd),
                    "prob": float(s.prob),
                })

            # ------------------------------
            # ADICIONAR AO OBJETO FINAL
            # ------------------------------
            items.append({
                "id": t.id,
                "saved_at": saved_at,
                "status": t.status,       # PENDING / FINISHED
                "result": t.result,       # GREEN / RED
                "final_odd": final_odd,
                "combined_prob": combined_prob,
                "selections": selections,
                "meta": t.meta
            })

        return {
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size,
            "items": items
        }

    finally:
        db.close()



# ====================================================================
#  RANKING DE JOGOS (baseado no stats_engine antigo)
# ====================================================================
@app.get("/ranking-jogos")
def ranking_jogos(days: int = 2):
    db = SessionLocal()
    today = datetime.now().date()
    end = today + timedelta(days=days)

    fixtures = db.query(Fixture).filter(
        Fixture.date >= datetime.combine(today, datetime.min.time()),
        Fixture.date <= datetime.combine(end, datetime.max.time())
    ).all()

    ranking = []

    for f in fixtures:
        home = compute_stats(f.home_team_id)
        away = compute_stats(f.away_team_id)

        if not home or not away:
            continue

        expected = (home["avg_match_goals"] + away["avg_match_goals"]) / 2
        score = 1 / (expected + 0.1)

        ranking.append({
            "fixture": f"{f.home_team.name} x {f.away_team.name}",
            "expected": expected,
            "score": score
        })

    ranking.sort(key=lambda x: x["score"], reverse=True)
    return ranking[:30]


# ====================================================================
#  SIMULAÇÃO DE BANCA (Monte Carlo)
# ====================================================================
class SimRequest(BaseModel):
    bankroll: float = 100.0
    stake: float = 0.02
    mode: int = 1
    target_odd: float = 1.15
    days: int = 30


@app.post("/simular-banca")
def simular_banca(req: SimRequest):
    bank = req.bankroll
    history = []

    for _ in range(req.days):

        ticket = find_ticket_for_target(
            mode=req.mode, target_odd=req.target_odd, days=1
        )

        if not ticket:
            history.append({"bank": bank, "msg": "Sem ticket no dia"})
            continue

        p = ticket["combined_prob"]
        o = ticket["final_odd"]
        stake = bank * req.stake

        bank = bank - stake + (stake * p * o)

        history.append({
            "ticket": ticket,
            "bank": bank
        })

    return {"final_bankroll": bank, "history": history}
    

@app.get("/jogos-futuros")
def jogos_futuros():
    db = SessionLocal()

    agora = datetime.now()

    fixtures = (
        db.query(Fixture)
        .options(
            joinedload(Fixture.league),
            joinedload(Fixture.home_team),
            joinedload(Fixture.away_team)
        )
        .filter(Fixture.status == "NS")
        .filter(Fixture.date >= agora)
        .order_by(Fixture.date.asc())
        .all()
    )

    response = []

    for fx in fixtures:
        response.append({
            "id": fx.id,
            "league": fx.league.name if fx.league else None,
            "league_id": fx.league.api_id if fx.league else None,

            "date": fx.date,
            "status": fx.status,

            "home": fx.home_team.name if fx.home_team else None,
            "home_id": fx.home_team.api_id if fx.home_team else None,

            "away": fx.away_team.name if fx.away_team else None,
            "away_id": fx.away_team.api_id if fx.away_team else None,

            # estatísticas opcionais
            "home_avg_scored": fx.home_avg_scored,
            "home_avg_conceded": fx.home_avg_conceded,
            "away_avg_scored": fx.away_avg_scored,
            "away_avg_conceded": fx.away_avg_conceded,
        })

    return {
        "total": len(response),
        "items": response
    }
    
    
@app.get("/jogos-historicos")
def jogos_historicos(
    start: str = None,
    end: str = None
):
    db = SessionLocal()

    agora = datetime.now()
    uma_semana = agora - timedelta(days=7)

    # --- PARSE DOS FILTROS ---
    if start:
        start_dt = datetime.fromisoformat(start)
    else:
        start_dt = uma_semana

    if end:
        end_dt = datetime.fromisoformat(end)
    else:
        end_dt = agora

    fixtures = (
        db.query(Fixture)
        .options(
            joinedload(Fixture.league),
            joinedload(Fixture.home_team),
            joinedload(Fixture.away_team)
        )
        .filter(Fixture.status == "FT")
        .filter(Fixture.date >= start_dt)
        .filter(Fixture.date <= end_dt)
        .order_by(Fixture.date.desc())  # <-- AGORA EM DESC
        .all()
    )

    response = []
    for fx in fixtures:
        response.append({
            "id": fx.id,
            "league": fx.league.name if fx.league else None,
            "league_id": fx.league.api_id if fx.league else None,
            "date": fx.date,
            "status": fx.status,
            "home": fx.home_team.name if fx.home_team else None,
            "home_id": fx.home_team.api_id if fx.home_team else None,
            "away": fx.away_team.name if fx.away_team else None,
            "away_id": fx.away_team.api_id if fx.away_team else None,
            "home_goals": fx.home_goals,
            "away_goals": fx.away_goals,
            "home_avg_scored": fx.home_avg_scored,
            "home_avg_conceded": fx.home_avg_conceded,
            "away_avg_scored": fx.away_avg_scored,
            "away_avg_conceded": fx.away_avg_conceded,
        })

    return {
        "total": len(response),
        "start": start_dt,
        "end": end_dt,
        "items": response
    }