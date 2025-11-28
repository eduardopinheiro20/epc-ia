from sqlalchemy import (
    Boolean, create_engine, Column, Integer, String, DateTime, ForeignKey,
    Float, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Defina DATABASE_URL no arquivo .env")

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# ============================================================
# LEAGUE
# ============================================================

class League(Base):
    __tablename__ = "leagues"
    id = Column(Integer, primary_key=True)
    api_id = Column(Integer, unique=True, index=True)
    name = Column(String)
    country = Column(String)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())


# ============================================================
# TEAM
# ============================================================

class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True)
    api_id = Column(Integer, unique=True, index=True)
    name = Column(String)
    country = Column(String)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())


# ============================================================
# FIXTURE — AGORA COMPLETO COM ESTATÍSTICAS
# ============================================================

class Fixture(Base):
    __tablename__ = "fixtures"

    id = Column(Integer, primary_key=True)
    api_id = Column(Integer, unique=True, index=True)

    league_id = Column(Integer, ForeignKey("leagues.id"))
    date = Column(DateTime(timezone=True))

    home_team_id = Column(Integer, ForeignKey("teams.id"))
    away_team_id = Column(Integer, ForeignKey("teams.id"))

    status = Column(String)
    home_goals = Column(Integer)
    away_goals = Column(Integer)

    # ------------ CAMPOS DE ESTATÍSTICAS (NOVOS) ------------
    home_avg_scored = Column(Float)         # média gols marcados (home)
    home_avg_conceded = Column(Float)       # média gols sofridos (home)
    home_recent_for = Column(JSON)          # últimos gols marcados
    home_recent_against = Column(JSON)      # últimos gols sofridos

    away_avg_scored = Column(Float)         # média gols marcados (away)
    away_avg_conceded = Column(Float)       # média gols sofridos (away)
    away_recent_for = Column(JSON)          # últimos gols marcados
    away_recent_against = Column(JSON)      # últimos gols sofridos

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())

    # ------------ RELACIONAMENTOS ------------
    league = relationship("League")
    home_team = relationship("Team", foreign_keys=[home_team_id])
    away_team = relationship("Team", foreign_keys=[away_team_id])


# ============================================================
# STANDING
# ============================================================

class Standing(Base):
    __tablename__ = "standings"
    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, ForeignKey("leagues.id"))
    team_id = Column(Integer, ForeignKey("teams.id"))
    season = Column(String)
    position = Column(Integer)
    points = Column(Integer)
    played = Column(Integer)
    won = Column(Integer)
    draw = Column(Integer)
    lost = Column(Integer)
    gf = Column(Integer)
    ga = Column(Integer)
    gd = Column(Integer)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


# ============================================================
# AUDIT
# ============================================================

class Audit(Base):
    __tablename__ = "audit"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    fixture_id = Column(Integer, ForeignKey("fixtures.id"))
    selection = Column(String)
    prob = Column(Float)
    odd = Column(Float)
    mode = Column(Integer)
    reason = Column(Text)


# ============================================================
# TICKET
# ============================================================

class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True)
    created_by = Column(String, nullable=True)   # opcional: user/email
    saved_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="PENDING")   # PENDING, FINISHED
    result = Column(String, nullable=True)        # GREEN, RED, UNKNOWN
    final_odd = Column(Float, nullable=False)
    combined_prob = Column(Float, nullable=True)
    applied_to_bankroll = Column(Boolean, default=False)  # se já foi aplicada na banca
    bankroll_id = Column(Integer, ForeignKey("bankrolls.id"), nullable=True)
    meta = Column(JSON, nullable=True)  # extra (motivos, explanation)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    signature = Column(String, unique=True, index=True)   # <-- ESSA LINHA É A QUE FALTA
    bankroll = relationship("Bankroll")

# ============================================================
# TICKET SELECTIONS
# ============================================================    
    
class TicketSelection(Base):
    __tablename__ = "ticket_selections"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"))
    fixture_id = Column(Integer, ForeignKey("fixtures.id"))
    market = Column(String)
    odd = Column(Float)
    prob = Column(Float)
    home_name = Column(String)
    away_name = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("Ticket", backref="selections")

# ============================================================
# Bankroll
# ============================================================

class Bankroll(Base):
    __tablename__ = "bankrolls"
    id = Column(Integer, primary_key=True)
    name = Column(String, default="Main")
    initial_amount = Column(Float, default=100.0)
    current_amount = Column(Float, default=100.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

# ============================================================
# CREATE TABLES
# ============================================================

def create_tables():
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    print("Criando tabelas...")
    create_tables()
    print("Tabelas criadas com sucesso!")
