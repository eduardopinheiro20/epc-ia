# src/run_collector.py
from apscheduler.schedulers.blocking import BlockingScheduler
from data_collector import collect_range, create_tables
import pytz
from datetime import datetime

# cria tabelas caso não existam
create_tables()

scheduler = BlockingScheduler(timezone=pytz.timezone("America/Sao_Paulo"))

# roda todo dia às 07:00
@scheduler.scheduled_job('cron', hour=7, minute=0)
def agendar_coleta():
    print("Iniciando coleta agendada —", datetime.now())
    collect_range(days_back=3, days_forward=2)  # coleta curta diária

if __name__ == "__main__":
    print("Scheduler started. Will collect everyday at 07:00 America/Sao_Paulo.")
    scheduler.start()
