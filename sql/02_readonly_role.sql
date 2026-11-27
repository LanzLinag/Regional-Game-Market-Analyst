-- Run as admin. Expects: -v agent_pw=...
CREATE ROLE agent_ro LOGIN PASSWORD :'agent_pw';

-- Connection and schema access
GRANT CONNECT ON DATABASE vgsales TO agent_ro;
GRANT USAGE ON SCHEMA public TO agent_ro;

-- Read-only on the data
GRANT SELECT ON games, sales_long TO agent_ro;

-- Belt and braces: guard rails even if something goes wrong
ALTER ROLE agent_ro SET default_transaction_read_only = on;
ALTER ROLE agent_ro SET statement_timeout = '5s';