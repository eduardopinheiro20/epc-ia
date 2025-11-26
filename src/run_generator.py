# src/run_generator.py

from datetime import datetime
from src.core.generator import find_ticket_for_target
from src.api.server import save_ticket_to_db


def generate_daily_ticket():
    """
    Gera o bilhete do dia usando o generator atual e salva no DB.
    Retorna o ticket gerado ou None.
    """

    print("=== EPC-IA :: Gerando bilhete diário ===")
    print("Horário:", datetime.now())

    # IA para gerar bilhete ultra seguro
    ticket = find_ticket_for_target(days=2, mode=1, target_odd=1.15)

    if not ticket:
        print("Nenhum ticket encontrado para hoje.")
        return None

    print("Ticket gerado. Salvando no banco...")
    ticket_id = save_ticket_to_db(ticket, mode=1)

    print(f"Bilhete salvo com sucesso! Ticket ID = {ticket_id}")
    return ticket


if __name__ == "__main__":
    generate_daily_ticket()
