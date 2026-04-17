#!/bin/bash
# Cria o banco de dados de desenvolvimento e aplica o mesmo schema do banco de produção.
# Este script é executado pelo PostgreSQL na inicialização do container,
# após o init.sql já ter criado a tabela no banco padrão (weather-db).

set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE "weather-db-dev";
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "weather-db-dev" \
    -f /docker-entrypoint-initdb.d/init.sql

echo "weather-db-dev criado com schema e dados de seed."
