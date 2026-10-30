FROM python:3.11-slim-bookworm
WORKDIR /app
COPY requirements-crypto.txt ./
RUN pip install --no-cache-dir -r requirements-crypto.txt
COPY src/modules/crypto/ ./src/modules/crypto/
USER 99:100
ENTRYPOINT ["python", "-m", "src.modules.crypto"]
CMD ["--config", "/config/positions.json", "--output", "/data/snapshot.json", "--watch"]
