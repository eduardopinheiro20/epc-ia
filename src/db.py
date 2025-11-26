from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, ForeignKey,
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
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    mode = Column(Integer)
    target_odd = Column(Float)
    combined_odd = Column(Float)
    combined_prob = Column(Float)
    selections = Column(Text)  # json
    status = Column(String)
    signature = Column(String, unique=True, index=True)


# ============================================================
# CREATE TABLES
# ============================================================

def create_tables():
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    print("Criando tabelas...")
    create_tables()
    print("Tabelas criadas com sucesso!")
