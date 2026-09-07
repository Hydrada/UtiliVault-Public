FROM python:3.12.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UTILIVAULT_CLOUD_RUNTIME=1 \
    UTILIVAULT_HOME=/var/lib/utilivault \
    UTILIVAULT_STATE_DIR=/var/lib/utilivault/state \
    UTILIVAULT_SECRETS_DIR=/run/secrets/utilivault \
    UTILIVAULT_FONT_REGULAR=/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf \
    UTILIVAULT_FONT_BOLD=/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates fonts-liberation2 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 utilivault

WORKDIR /app
COPY deploy/cloud/requirements.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir --requirement /tmp/requirements.lock

COPY . /app
USER utilivault

CMD ["python", "field_intake_watcher.py", "--once"]

