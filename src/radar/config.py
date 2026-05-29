"""全局配置 - 从环境变量加载，带类型和默认值"""
from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings

ROOT_DIR = Path(__file__).parents[2]  # radar/  (src/radar/config.py → src/radar → src → radar)
DATA_DIR = ROOT_DIR / "data"
OUTPUTS_DIR = ROOT_DIR / "outputs"
LOGS_DIR = ROOT_DIR / "logs"

for d in [DATA_DIR, OUTPUTS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


class LLMProfile(str, Enum):
    zhipu = "zhipu"
    heyi = "heyi"
    yunwu = "yunwu"
    ollama = "ollama"
    openai = "openai"


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # ── 数据库 ────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://radar:radar@localhost:5432/radar",
        alias="DATABASE_URL",
    )
    sync_database_url: str = Field(
        default="postgresql+psycopg2://radar:radar@localhost:5432/radar",
        alias="SYNC_DATABASE_URL",
    )

    # ── LLM ───────────────────────────────────────
    # Default provider: yunwu MiniMax-M2.7 (the one brain shared with
    # heyi-eval, with a working key). The ``zhipu`` GLM-5.1 profile is
    # ready and one ``LLM_PROFILE=zhipu`` away once a valid Zhipu key
    # exists.
    llm_profile: LLMProfile = Field(default=LLMProfile.yunwu, alias="LLM_PROFILE")

    zhipu_api_key: str = Field(default="", alias="ZHIPU_API_KEY")
    zhipu_base_url: str = Field(
        default="https://open.bigmodel.cn/api/paas/v4", alias="ZHIPU_BASE_URL"
    )
    zhipu_model: str = Field(default="glm-5.1", alias="ZHIPU_MODEL")

    yunwu_api_key: str = Field(default="", alias="YUNWU_API_KEY")
    yunwu_base_url: str = Field(default="https://yunwu.ai/v1", alias="YUNWU_BASE_URL")
    yunwu_model: str = Field(default="MiniMax-M2.7", alias="YUNWU_MODEL")

    heyi_api_key: str = Field(default="sk-heyi-local", alias="HEYI_API_KEY")
    heyi_base_url: str = Field(default="http://heyi.local:8000/v1", alias="HEYI_BASE_URL")
    heyi_model: str = Field(default="qwen3-235b", alias="HEYI_MODEL")

    ollama_base_url: str = Field(default="http://localhost:11434/v1", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3.1:8b", alias="OLLAMA_MODEL")
    ollama_api_key: str = Field(default="ollama", alias="OLLAMA_API_KEY")

    # ── GitHub ────────────────────────────────────
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    github_crawl_interval: str = Field(default="6h", alias="GITHUB_CRAWL_INTERVAL")

    # ── Reddit ────────────────────────────────────
    reddit_client_id: str = Field(default="", alias="REDDIT_CLIENT_ID")
    reddit_client_secret: str = Field(default="", alias="REDDIT_CLIENT_SECRET")
    reddit_username: str = Field(default="", alias="REDDIT_USERNAME")
    reddit_password: str = Field(default="", alias="REDDIT_PASSWORD")
    reddit_user_agent: str = Field(default="radar/0.1.0", alias="REDDIT_USER_AGENT")
    reddit_crawl_interval: str = Field(default="1h", alias="REDDIT_CRAWL_INTERVAL")

    # ── 报告 ──────────────────────────────────────
    report_projects_cron: str = Field(default="0 6 * * *", alias="REPORT_PROJECTS_CRON")
    report_communities_cron: str = Field(default="0 6 * * *", alias="REPORT_COMMUNITIES_CRON")
    report_retention_days: int = Field(default=90, alias="REPORT_RETENTION_DAYS")

    # ── Web ───────────────────────────────────────
    web_host: str = Field(default="0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(default=7090, alias="WEB_PORT")
    web_debug: bool = Field(default=False, alias="WEB_DEBUG")

    # ── 监控 ──────────────────────────────────────
    token_expiry_warning_hours: int = Field(default=48, alias="TOKEN_EXPIRY_WARNING_HOURS")
    source_fail_threshold: int = Field(default=5, alias="SOURCE_FAIL_THRESHOLD")
    data_stale_seconds: int = Field(default=7200, alias="DATA_STALE_SECONDS")
    disk_low_gb: float = Field(default=5.0, alias="DISK_LOW_GB")
    macos_notify: bool = Field(default=True, alias="MACOS_NOTIFY")

    # ── 抓取 ──────────────────────────────────────
    max_items_per_run: int = Field(default=500, alias="MAX_ITEMS_PER_RUN")
    raw_blob_retention_days: int = Field(default=0, alias="RAW_BLOB_RETENTION_DAYS")

    # ── heyi-eval 实测结果（radar×heyi-eval 合并：结果回流侧）──────────
    # heyi-eval 把 project/skill lane 的 run 落在
    # ``{heyi_eval_data}/{project,skill}_lane/runs/<run_id>/state.json``。
    # radar 同机只读这些文件，渲染「实测结果」页。
    heyi_eval_data: str = Field(
        default="/home/ai/heyi-eval-data", alias="HEYI_EVAL_DATA"
    )

    # ── 安全 ──────────────────────────────────────
    credential_encryption_key: str = Field(default="", alias="CREDENTIAL_ENCRYPTION_KEY")

    # ── 日志 ──────────────────────────────────────
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_dir: Path = Field(default=LOGS_DIR, alias="LOG_DIR")

    @property
    def llm_api_key(self) -> str:
        mapping = {
            LLMProfile.zhipu: self.zhipu_api_key,
            LLMProfile.heyi: self.heyi_api_key,
            LLMProfile.yunwu: self.yunwu_api_key,
            LLMProfile.ollama: self.ollama_api_key,
            LLMProfile.openai: os.environ.get("OPENAI_API_KEY", ""),
        }
        return mapping[self.llm_profile]

    @property
    def llm_base_url(self) -> str:
        mapping = {
            LLMProfile.zhipu: self.zhipu_base_url,
            LLMProfile.heyi: self.heyi_base_url,
            LLMProfile.yunwu: self.yunwu_base_url,
            LLMProfile.ollama: self.ollama_base_url,
            LLMProfile.openai: "https://api.openai.com/v1",
        }
        return mapping[self.llm_profile]

    @property
    def llm_model(self) -> str:
        mapping = {
            LLMProfile.zhipu: self.zhipu_model,
            LLMProfile.heyi: self.heyi_model,
            LLMProfile.yunwu: self.yunwu_model,
            LLMProfile.ollama: self.ollama_model,
            LLMProfile.openai: "gpt-4o-mini",
        }
        return mapping[self.llm_profile]

    # ── 便捷属性（app.py / database.py 使用）────────────────────────────

    @property
    def debug(self) -> bool:
        return self.web_debug

    @property
    def db_async_url(self) -> str:
        return self.database_url

    @property
    def base_dir(self) -> Path:
        return ROOT_DIR

    @property
    def output_dir(self) -> Path:
        # 支持测试时通过 _output_dir_override 覆盖
        override = self.__dict__.get("_output_dir_override")
        if override is not None:
            return Path(override)
        return OUTPUTS_DIR

    # ── 工具方法 ──────────────────────────────────────────────────────────

    def interval_seconds(self, interval_str: str) -> int:
        """将 '6h', '1h', '15min', 'daily', 'weekly' 转换为秒"""
        mapping = {
            "15min": 900,
            "1h": 3600,
            "6h": 21600,
            "daily": 86400,
            "weekly": 604800,
        }
        return mapping.get(interval_str, 3600)


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# 全局单例，供 `from radar.config import settings` 使用
settings: Settings = get_settings()
