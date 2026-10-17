# One image for the field-device simulator, the SCADA gateway and the FAT runner.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends iproute2 iputils-ping tcpdump \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home /app --shell /usr/sbin/nologin bess

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bess_lab ./bess_lab
COPY config ./config
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh && mkdir -p /app/reports && chown bess:bess /app/reports

ENV PYTHONUNBUFFERED=1 BESS_CONFIG_DIR=/app/config
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "-m", "bess_lab.gateway.main"]
