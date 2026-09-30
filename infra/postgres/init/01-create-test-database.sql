-- The test suite runs against its own database so a test run never touches
-- development data. The script runs as POSTGRES_USER, which therefore owns it.
CREATE DATABASE datapilot_test;
