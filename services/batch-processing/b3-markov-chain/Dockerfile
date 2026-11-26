FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[db,kafka]"
CMD ["python", "-m", "b3_markov.main", "--source", "db", "--announce"]
