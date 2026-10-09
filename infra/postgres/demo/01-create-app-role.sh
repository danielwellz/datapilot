#!/bin/sh
# Creates the role the API connects as in the demo stack.
#
# The Docker image runs this once, when the data volume is empty, as
# POSTGRES_USER: the owner of the database, which runs the migrations, the
# seed and db-roles from the one-shot migrate job. The API itself connects as
# APP_DB_USER, which is no superuser and owns nothing: it may read and write
# rows, but not create, alter or drop objects, change roles or read files on
# the server. Default privileges extend its grants to every table the
# migrations create later.
set -eu

: "${APP_DB_USER:?set APP_DB_USER to the role the API connects as}"
: "${APP_DB_PASSWORD:?set APP_DB_PASSWORD}"

psql --no-psqlrc -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v owner="$POSTGRES_USER" -v app_user="$APP_DB_USER" \
    -v app_password="$APP_DB_PASSWORD" -v database="$POSTGRES_DB" <<'SQL'
CREATE ROLE :"app_user" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'app_password';
GRANT CONNECT ON DATABASE :"database" TO :"app_user";
GRANT USAGE ON SCHEMA public TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO :"app_user";
SQL
