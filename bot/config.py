from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    house_channel_id: int
    house_channel_invite_link: str = ""
    admin_ids: str = ""
    timezone: str = "Europe/Rome"
    db_path: str = "./data/housemate.db"
    membership_recheck_hours: int = 6
    run_mode: str = "polling"

    @property
    def admin_id_set(self) -> set[int]:
        return {int(x) for x in self.admin_ids.split(",") if x.strip()}

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"


settings = Settings()
