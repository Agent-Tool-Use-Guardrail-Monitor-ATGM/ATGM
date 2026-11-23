# Build context: the repository's services/ directory (S08 depends on the B3 package):
#   docker build -f services/stream-processing/s08-markov-order-check/Dockerfile -t atgm-markov-order-check services
FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# B3 Markov chain: the model arithmetic S08 scores with (b3_markov.domain)
COPY batch-processing/b3-markov-chain/pyproject.toml /opt/b3-markov-chain/pyproject.toml
COPY batch-processing/b3-markov-chain/src/ /opt/b3-markov-chain/src/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir /opt/b3-markov-chain

COPY stream-processing/s08-markov-order-check/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY stream-processing/s08-markov-order-check/pyproject.toml .
COPY stream-processing/s08-markov-order-check/src/ ./src/
COPY stream-processing/s08-markov-order-check/tests/ ./tests/

RUN pip install --no-cache-dir .

CMD ["python", "-m", "markov_order_check.consumer"]
