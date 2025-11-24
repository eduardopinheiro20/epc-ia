from datetime import datetime
import requests
import os
from dotenv import load_dotenv

from src.core.stats_engine import compare_teams
from src.core.generator import generate, format_ticket

# Carregar variáveis de ambiente (.env)
load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = os.getenv("BASE_URL")

HEADERS = {
    "x-apisports-key": API_KEY
}

# Ligas principais
ligas_permitidas = [
    "Premier League",
    "La Liga",
    "Serie A",
    "Ligue 1",
    "Bundesliga",
    "Championship",
    "Jupiler Pro League",
    "Primeira Liga",
    "Liga Profesional Argentina",
    "Serie B",
    "Brasileirão",
    "Brasileirão Série A",
    "Brasileirão Série B"
]


def buscar_jogos_do_dia():
    hoje = datetime.now().strftime("%Y-%m-%d")
    url = f"{BASE_URL}/fixtures?date={hoje}&timezone=America/Sao_Paulo"
    response = requests.get(url, headers=HEADERS)

    if response.status_code != 200:
        print("Erro ao buscar jogos:", response.text)
        return []

    dados = response.json()
    return dados.get("response", [])


def main():
    print("============== EPC-IA ==============")
    print("     IA de Bilhetes Super Seguros   ")
    print("====================================\n")

    print("1️⃣  Buscando jogos do dia...\n")
    jogos = buscar_jogos_do_dia()

    if not jogos:
        print("Nenhum jogo encontrado.")
        return

    print(f"{len(jogos)} jogos encontrados.\n")

    print("2️⃣  Filtrando ligas principais...\n")

    jogos_ligas_grandes = []
    for jogo in jogos:
        liga = jogo["league"]["name"]
        if liga in ligas_permitidas:
            jogos_ligas_grandes.append(jogo)

    if not jogos_ligas_grandes:
        print("⚠️ Nenhum jogo de grandes ligas hoje.")
        return

    print(f"{len(jogos_ligas_grandes)} jogos de grandes ligas.\n")

    print("3️⃣  Executando IA do Gerador de Aposta...\n")

    ticket = generate(target_odd=1.15, mode=1)  # Ultra seguro, odd 1.15

    if ticket:
        print("🎉 MELHOR APOSTA DO DIA ENCONTRADA!")
        print("------------------------------------")
        print(format_ticket(ticket))
    else:
        print("⚠️ Nenhuma aposta segura disponível hoje.")


if __name__ == "__main__":
    main()
