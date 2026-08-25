-- Runs once, on a fresh postgres volume. The test suite truncates every table
-- between tests, so it needs a database of its own rather than the development
-- one. Existing volumes predate this: `make test-db` creates it after the fact.
CREATE DATABASE oncall_test;
