FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY .streamlit ./.streamlit
RUN pip install --no-cache-dir ".[app]"
EXPOSE 8501
CMD ["streamlit", "run", "src/review_ui/app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
