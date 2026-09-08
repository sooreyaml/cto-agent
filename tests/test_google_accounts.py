import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from src.google.models import GoogleAccount
from src.google.service import (
    delete_account,
    is_google_connect_command,
    label_account,
    list_accounts,
    load_account,
    set_default_account,
    upsert_google_account,
)
from src.models import Base


@pytest.fixture
async def google_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=[GoogleAccount.__table__])
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("src.google.service.async_session_factory", factory)
    yield factory
    await engine.dispose()


def test_add_google_connect_commands() -> None:
    assert is_google_connect_command("add google account")
    assert is_google_connect_command("connect another google")


@pytest.mark.asyncio
async def test_upsert_keeps_two_emails(google_db) -> None:
    first = await upsert_google_account(
        slack_user_id="owner",
        refresh_token="r1",
        access_token="a1",
        token_expiry=None,
        scopes="gmail",
        email="work@example.com",
    )
    second = await upsert_google_account(
        slack_user_id="owner",
        refresh_token="r2",
        access_token="a2",
        token_expiry=None,
        scopes="gmail",
        email="personal@example.com",
        label="personal",
    )
    assert first.is_default is True
    assert second.is_default is False
    accounts = await list_accounts()
    assert {item["email"] for item in accounts} == {"work@example.com", "personal@example.com"}
    again = await upsert_google_account(
        slack_user_id="owner",
        refresh_token="r1b",
        access_token="a1b",
        token_expiry=None,
        scopes="gmail",
        email="work@example.com",
    )
    assert again.id == first.id
    assert again.refresh_token == "r1b"
    assert len(await list_accounts()) == 2


@pytest.mark.asyncio
async def test_resolve_by_label_and_default(google_db) -> None:
    await upsert_google_account(
        slack_user_id="owner",
        refresh_token="r1",
        access_token=None,
        token_expiry=None,
        scopes=None,
        email="work@example.com",
    )
    await upsert_google_account(
        slack_user_id="owner",
        refresh_token="r2",
        access_token=None,
        token_expiry=None,
        scopes=None,
        email="home@example.com",
        label="personal",
    )
    found = await load_account("personal")
    assert found is not None
    assert found.email == "home@example.com"
    defaulted = await set_default_account("home@example.com")
    assert defaulted.is_default is True
    current = await load_account()
    assert current is not None
    assert current.email == "home@example.com"
    labeled = await label_account("work@example.com", "work")
    assert labeled.label == "work"
    removed = await delete_account("personal")
    assert removed is True
    leftover = await list_accounts()
    assert len(leftover) == 1
    assert leftover[0]["is_default"] is True
    assert leftover[0]["email"] == "work@example.com"
