FROM python:3.9

WORKDIR /app

COPY requirements.txt .

# evita qualquer progress bar
ENV PIP_PROGRESS_BAR=off
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY .env .

CMD ["uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
