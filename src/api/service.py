# src/api/service.py

from pydantic import BaseModel
from src.db import SessionLocal, Standing, Ticket, Audit
import hashlib
import json


class SaveTicketRequest(BaseModel):
    ticket: dict
    mode: int = 1
    comment: str | None = None

def make_ticket_signature(ticket: dict):
    raw = json.dumps(ticket.get("selections", []), sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()

def save_ticket_to_db(ticket: dict, mode: int = 1, status: str = "PUBLISHED"):
    db = SessionLocal()
    try:
        # --- 1. Gerar assinatura única do bilhete ---
        signature = make_ticket_signature(ticket)

        # --- 2. Verificar se já existe esse bilhete ---
        existing = db.query(Ticket).filter(Ticket.signature == signature).first()

        if existing:
            return {"id": existing.id, "duplicate": True} # Já salvo → retorna ID existente

        # --- 3. Criar bilhete novo ---
        t = Ticket()
        t.mode = mode
        t.signature = signature
        t.target_odd = ticket.get("target_odd")
        t.combined_odd = ticket.get("final_odd")
        t.combined_prob = ticket.get("combined_prob")

        import json
        t.selections = json.dumps(ticket.get("selections", []), ensure_ascii=False)
        t.status = status

        db.add(t)
        db.commit()
        db.refresh(t)

        # --- 4. Auditoria ---
        for sel in ticket.get("selections", []):
            a = Audit()
            a.fixture_id = sel.get("fixture_id")
            a.selection = sel.get("market")
            a.prob = sel.get("prob")
            a.odd = sel.get("odd")
            a.mode = mode
            a.reason = sel.get("explain") or ""

            db.add(a)

        db.commit()
        return {"id": t.id, "duplicate": False}

    except Exception as e:
        db.rollback()
        raise

    finally:
        db.close()