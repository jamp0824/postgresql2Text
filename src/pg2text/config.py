"""
설정 모듈 — 환경변수 기반 설정 관리 (pydantic-settings)
"""

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """애플리케이션 설정"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    # ── Gemini ───────────────────────────────────────────
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    pg2text_model: str = Field(default="gemini-3.5-flash", alias="PG2TEXT_MODEL")

    # ── PostgreSQL ───────────────────────────────────────
    pg_host: str = Field(default="localhost", alias="PG_HOST")
    pg_port: int = Field(default=5432, alias="PG_PORT")
    pg_database: str = Field(default="postgres", alias="PG_DATABASE")
    pg_user: str = Field(default="postgres", alias="PG_USER")
    pg_password: str = Field(default="", alias="PG_PASSWORD")

    # ── 출력 설정 ────────────────────────────────────────
    pg2text_output_dir: Path = Field(default=Path("./output"), alias="PG2TEXT_OUTPUT_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def database_url(self) -> str:
        """SQLAlchemy 연결 URL 반환"""
        return (
            f"postgresql+psycopg2://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )

    @property
    def output_dir(self) -> Path:
        """출력 디렉터리 (없으면 생성)"""
        self.pg2text_output_dir.mkdir(parents=True, exist_ok=True)
        return self.pg2text_output_dir


# 싱글턴 설정 인스턴스
settings = Settings()
