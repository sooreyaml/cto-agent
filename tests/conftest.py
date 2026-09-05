import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://cto:cto@localhost:5432/cto_agent"
os.environ["OPENROUTER_API_KEY"] = "test-openrouter"
os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"
os.environ["SLACK_SIGNING_SECRET"] = "test-signing-secret"
os.environ["SLACK_USER_ID"] = "UTEST"
os.environ["NODE_ENV"] = "test"
os.environ["CRON_SECRET"] = "cron-test-secret"
