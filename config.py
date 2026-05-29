"""BriefConfig — profile loader for the local pipeline."""
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class BriefConfig:
    name: str
    profile_id: str
    sources: list[dict]
    system_prompt: str
    youtube_synthesis_prompt: str
    title: str = ""
    llm_provider: str = "auto"
    llm_model: str | None = None

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BriefConfig":
        path = Path(path).resolve()
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        profile_dir = path.parent
        profile_id = profile_dir.name

        raw_sources = data.get("sources", "default")
        if raw_sources == "default":
            from sources import SOURCES
            sources = SOURCES
        else:
            sources = raw_sources

        prompts_cfg = data.get("prompts") or {}
        system_file = prompts_cfg.get("system_file")
        system_prompt = (
            (profile_dir / system_file).read_text(encoding="utf-8")
            if system_file
            else _default_system_prompt()
        )

        youtube_file = prompts_cfg.get("youtube_file")
        youtube_prompt = (
            (profile_dir / youtube_file).read_text(encoding="utf-8")
            if youtube_file
            else _default_youtube_prompt()
        )

        llm_cfg = data.get("llm") or {}
        output_cfg = data.get("output") or {}

        return cls(
            name=data["name"],
            profile_id=profile_id,
            sources=sources,
            system_prompt=system_prompt,
            youtube_synthesis_prompt=youtube_prompt,
            title=output_cfg.get("title", data["name"]),
            llm_provider=llm_cfg.get("provider", "auto"),
            llm_model=llm_cfg.get("model"),
        )

    @classmethod
    def default(cls) -> "BriefConfig":
        return cls.from_yaml(
            Path(__file__).parent / "profiles" / "ai_news" / "profile.yaml"
        )


def _default_system_prompt() -> str:
    from prompts import SYSTEM_PROMPT
    return SYSTEM_PROMPT


def _default_youtube_prompt() -> str:
    from prompts import YOUTUBE_SYNTHESIS_PROMPT
    return YOUTUBE_SYNTHESIS_PROMPT
