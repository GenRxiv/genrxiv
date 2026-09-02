FROM python:3.12-slim

# Tectonic (self-contained LaTeX engine) + Pandoc, no full TeXLive needed
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates pandoc \
    && curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh \
    && mv tectonic /usr/local/bin/tectonic \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 convertor
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN mkdir -p /data && chown convertor:convertor /data

USER convertor

# No inbound ports other than the API; the compose network should NOT give
# this container internet access at compile time (see docker-compose.yml).
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
