FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY odiro ./odiro
RUN pip install --no-cache-dir .

COPY scripts ./scripts
COPY data ./data
COPY cache ./cache

EXPOSE 8501
CMD ["streamlit", "run", "odiro/app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
