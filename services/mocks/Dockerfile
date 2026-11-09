FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[kafka]"
# docker-compose.yml chooses the entry point: atgm_mocks.run_agents or atgm_mocks.run_scorer
CMD ["python", "-m", "atgm_mocks.run_agents"]
