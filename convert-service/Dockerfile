FROM python:3.12-slim

# Pandoc for conversion + Tectonic (LaTeX engine for PDF output)
# libgraphite2 / libharfbuzz / fontconfig are Tectonic runtime deps,
# installed explicitly so autoremove cannot strip them
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates pandoc curl \
        libgraphite2-3 libharfbuzz0b fontconfig \
        librsvg2-bin \
    && curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh \
    && mv tectonic /usr/local/bin/tectonic \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Create the runtime user before warming the cache
RUN useradd -m -u 1000 convertor

# Pre-warm the Tectonic cache as the runtime user, so the first real
# compile doesn't need to download the LaTeX bundle (the runtime
# container may have no internet access)
USER convertor
RUN echo '\\documentclass{article}\\begin{document}X\\end{document}' > /tmp/warm.tex \
    && tectonic /tmp/warm.tex -o /tmp \
    && rm -f /tmp/warm.tex /tmp/warm.pdf

USER root
WORKDIR /app

COPY convert-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY convert-service/app.py .

RUN mkdir -p /data && chown convertor:convertor /data

USER convertor

# No inbound ports other than the API; the compose network should NOT give
# this container internet access at compile time (see docker-compose.yml).
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
