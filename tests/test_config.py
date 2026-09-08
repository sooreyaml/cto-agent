from src.config import async_database_url_from


def test_async_database_url_from_upgrades_postgres() -> None:
    assert (
        async_database_url_from("postgres://cto:cto@db:5432/cto_agent")
        == "postgresql+asyncpg://cto:cto@db:5432/cto_agent"
    )


def test_async_database_url_from_adds_asyncpg() -> None:
    assert (
        async_database_url_from("postgresql://cto:cto@db:5432/cto_agent")
        == "postgresql+asyncpg://cto:cto@db:5432/cto_agent"
    )
