# SPAgo database image: PostgreSQL 15 + RDKit cartridge.
#
# Built from Debian (not the official postgres image) because Debian bookworm
# ships a distro-consistent pair: postgresql-15 + postgresql-15-rdkit.
# See docs/adr/0001-m0-foundation-data-path.md decision 2.
FROM debian:bookworm-slim

ENV PG_VERSION=15 \
    PG_BIN=/usr/lib/postgresql/15/bin \
    PGDATA=/var/lib/postgresql/data \
    POSTGRES_DB=spago \
    POSTGRES_USER=spago \
    POSTGRES_PASSWORD=spago

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      postgresql-15 \
      postgresql-15-rdkit \
      postgresql-client-15 \
 && rm -rf /var/lib/apt/lists/*

COPY docker/db/init-spago-db.sh /usr/local/bin/init-spago-db.sh
COPY docker/db/ensure-rdkit-extension.sql /usr/local/share/ensure-rdkit-extension.sql
RUN chmod +x /usr/local/bin/init-spago-db.sh

# Healthcheck used by docker-compose (defined there so the env vars apply).
EXPOSE 5432

ENTRYPOINT ["/usr/local/bin/init-spago-db.sh"]
