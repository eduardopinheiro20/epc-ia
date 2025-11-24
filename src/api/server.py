from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
from src.db import SessionLocal, Fixture, Ticket
from src.core.generator import find_ticket_for_target, generate_ticket, explain_ticket, candidate_markets_for_fixture
from src.core.stats_engine import compute_stats

import json

app = FastAPI(title="EPC-IA Betting AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now()}

@app.get("/melhor-aposta")
def melhor_aposta(mode: int = 1, target_odd: float = 1.15, days: int = 2):
    ticket = find_ticket_for_target(days=days, mode=mode, target_odd=target_odd)
    if not ticket:
        return {"found": False}
    return ticket

@app.get("/bilhete-do-dia")
def bilhete_do_dia(mode: int = 1, target_odd: float = 1.15):
    # 1) Carrega os jogos do DB (hoje + amanhã)
    fixtures = load_fixtures_from_db(days_span=2)

    # 2) Gera o ticket com a nova IA Poisson + heurística
    ticket = generate_ticket(
        fixtures,
        mode=mode,
        target_odd=target_odd,
        days_span=2
    )

    if not ticket or not ticket.get("selections"):
        return {
            "found": False,
            "msg": "Nenhuma seleção segura encontrada para o bilhete do dia."
        }

    # 3) (Opcional) adicionar explicação do bilhete
    ticket["explain"] = explain_ticket(ticket)

    return {"found": True, "ticket": ticket}

@app.get("/historico-tickets")
def historico_tickets(limit: int = 30):
    db = SessionLocal()
    items = db.query(Ticket).order_by(Ticket.created_at.desc()).limit(limit).all()
    out = []
    for it in items:
        out.append({
            "id": it.id,
            "created_at": it.created_at,
            "combined_odd": it.combined_odd,
            "combined_prob": it.combined_prob,
            "selections": json.loads(it.selections)
        })
    return out

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
        ticket = find_ticket_for_target(mode=req.mode, target_odd=req.target_odd, days=1)
        if not ticket:
            history.append({"bank": bank, "msg": "Sem ticket no dia"})
            continue

        p = ticket["combined_prob"]
        o = ticket["combined_odd"]
        stake = bank * req.stake

        bank = bank - stake + (stake * p * o)
        history.append({
            "ticket": ticket,
            "bank": bank
        })

    return {"final_bankroll": bank, "history": history}
