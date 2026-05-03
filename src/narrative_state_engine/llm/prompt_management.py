from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROMPT_METADATA_HEADER = "# Prompt Metadata"


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    version: str
    task: str
    output_contract: str
    content: str
    path: Path
    content_hash: str


@dataclass(frozen=True)
class PromptBinding:
    purpose: str
    task_prompt: str


@dataclass(frozen=True)
class PromptProfile:
    id: str
    version: str
    global_prompt: str
    reasoning_mode: str
    bindings: dict[str, PromptBinding]


@dataclass(frozen=True)
class ComposedPrompt:
    system_content: str
    metadata: dict[str, str]


class PromptRegistry:
    def __init__(self, prompt_dir: str | Path | None = None) -> None:
        self.prompt_dir = _resolve_prompt_dir(prompt_dir)

    def load_profile(self, profile_id: str | None = None) -> PromptProfile:
        requested = (profile_id or os.getenv("NOVEL_AGENT_PROMPT_PROFILE", "default") or "default").strip()
        path = self.prompt_dir / "profiles" / f"{requested}.yaml"
        data = _parse_simple_yaml(path.read_text(encoding="utf-8"))
        bindings_raw = data.get("bindings")
        if not isinstance(bindings_raw, dict):
            raise ValueError(f"prompt profile `{requested}` must define bindings")
        bindings = {
            str(purpose): PromptBinding(purpose=str(purpose), task_prompt=str(task_prompt))
            for purpose, task_prompt in bindings_raw.items()
            if str(purpose).strip() and str(task_prompt).strip()
        }
        profile = PromptProfile(
            id=_required_str(data, "id", path=path),
            version=_required_str(data, "version", path=path),
            global_prompt=_required_str(data, "global_prompt", path=path),
            reasoning_mode=str(data.get("reasoning_mode") or "internal").strip() or "internal",
            bindings=bindings,
        )
        if not profile.bindings:
            raise ValueError(f"prompt profile `{requested}` has no valid bindings")
        return profile

    def get_binding(self, purpose: str, profile: PromptProfile | None = None) -> PromptBinding:
        active_profile = profile or self.load_profile()
        key = str(purpose or "").strip()
        binding = active_profile.bindings.get(key)
        if binding is None:
            raise KeyError(f"no prompt binding configured for purpose `{key}` in profile `{active_profile.id}`")
        return binding

    def load_global_prompt(self, prompt_name: str) -> PromptTemplate:
        return self._load_template(self.prompt_dir / "global" / f"{prompt_name}.md", expected_task="global")

    def load_task_prompt(self, prompt_name: str, *, expected_task: str) -> PromptTemplate:
        return self._load_template(self.prompt_dir / "tasks" / f"{prompt_name}.md", expected_task=expected_task)

    def _load_template(self, path: Path, *, expected_task: str) -> PromptTemplate:
        raw = path.read_text(encoding="utf-8")
        front_matter, content = _split_front_matter(raw, path=path)
        template = PromptTemplate(
            id=_required_str(front_matter, "id", path=path),
            version=_required_str(front_matter, "version", path=path),
            task=_required_str(front_matter, "task", path=path),
            output_contract=_required_str(front_matter, "output_contract", path=path),
            content=content.strip(),
            path=path,
            content_hash=_hash_text(content),
        )
        if template.task != expected_task:
            raise ValueError(f"prompt `{path}` declares task `{template.task}`, expected `{expected_task}`")
        if not template.content:
            raise ValueError(f"prompt `{path}` has empty content")
        return template


class PromptComposer:
    def __init__(self, registry: PromptRegistry | None = None) -> None:
        self.registry = registry or PromptRegistry()

    def compose_system_prompt(self, *, purpose: str) -> ComposedPrompt:
        profile = self.registry.load_profile()
        binding = self.registry.get_binding(purpose, profile)
        global_prompt = self.registry.load_global_prompt(profile.global_prompt)
        task_prompt = self.registry.load_task_prompt(binding.task_prompt, expected_task=purpose)
        reasoning_mode = os.getenv("NOVEL_AGENT_REASONING_MODE", profile.reasoning_mode).strip() or "internal"
        metadata = {
            "prompt_profile": profile.id,
            "prompt_profile_version": profile.version,
            "global_prompt_id": global_prompt.id,
            "global_prompt_version": global_prompt.version,
            "global_prompt_hash": global_prompt.content_hash,
            "task_prompt_id": task_prompt.id,
            "task_prompt_version": task_prompt.version,
            "task_prompt_hash": task_prompt.content_hash,
            "reasoning_mode": reasoning_mode,
        }
        system_content = "\n\n".join(
            [
                global_prompt.content,
                task_prompt.content,
                _format_metadata_block(metadata),
            ]
        )
        return ComposedPrompt(system_content=system_content, metadata=metadata)


def compose_system_prompt(*, purpose: str) -> ComposedPrompt:
    return PromptComposer().compose_system_prompt(purpose=purpose)


def extract_prompt_metadata_from_messages(messages: list[dict[str, Any]] | None) -> dict[str, str]:
    for item in messages or []:
        if str(item.get("role", "")) != "system":
            continue
        metadata = _extract_metadata_block(str(item.get("content", "")))
        if metadata:
            return metadata
    return {}


def _resolve_prompt_dir(prompt_dir: str | Path | None) -> Path:
    raw = prompt_dir or os.getenv("NOVEL_AGENT_PROMPT_DIR", "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = _repo_root() / path
        return path
    return _repo_root() / "prompts"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _split_front_matter(raw: str, *, path: Path) -> tuple[dict[str, Any], str]:
    text = raw.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError(f"prompt `{path}` must start with front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError(f"prompt `{path}` has unterminated front matter")
    front_matter = _parse_simple_yaml_text(text[4:end])
    content = text[end + len("\n---\n") :]
    return front_matter, content


def _parse_simple_yaml(path_text: str) -> dict[str, Any]:
    return _parse_simple_yaml_text(path_text)


def _parse_simple_yaml_text(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_map_key: str | None = None
    for raw_line in text.replace("\r\n", "\n").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith("  ") and current_map_key:
            key, value = _split_key_value(raw_line.strip())
            nested = data.setdefault(current_map_key, {})
            if not isinstance(nested, dict):
                raise ValueError(f"`{current_map_key}` cannot mix scalar and mapping values")
            nested[key] = value
            continue
        key, value = _split_key_value(raw_line.strip())
        if value == "":
            data[key] = {}
            current_map_key = key
        else:
            data[key] = value
            current_map_key = None
    return data


def _split_key_value(line: str) -> tuple[str, str]:
    if ":" not in line:
        raise ValueError(f"invalid prompt profile/front matter line: {line}")
    key, value = line.split(":", 1)
    key = key.strip()
    if not key:
        raise ValueError(f"invalid empty key in line: {line}")
    return key, value.strip().strip('"').strip("'")


def _required_str(data: dict[str, Any], key: str, *, path: Path) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise ValueError(f"`{key}` is required in `{path}`")
    return value


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _format_metadata_block(metadata: dict[str, str]) -> str:
    rows = [PROMPT_METADATA_HEADER]
    for key in [
        "prompt_profile",
        "prompt_profile_version",
        "global_prompt_id",
        "global_prompt_version",
        "global_prompt_hash",
        "task_prompt_id",
        "task_prompt_version",
        "task_prompt_hash",
        "reasoning_mode",
    ]:
        rows.append(f"{key}: {metadata.get(key, '')}")
    return "\n".join(rows)


def _extract_metadata_block(system_content: str) -> dict[str, str]:
    marker = system_content.find(PROMPT_METADATA_HEADER)
    if marker < 0:
        return {}
    metadata: dict[str, str] = {}
    for raw_line in system_content[marker + len(PROMPT_METADATA_HEADER) :].splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# "):
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in {
            "prompt_profile",
            "prompt_profile_version",
            "global_prompt_id",
            "global_prompt_version",
            "global_prompt_hash",
            "task_prompt_id",
            "task_prompt_version",
            "task_prompt_hash",
            "reasoning_mode",
        }:
            metadata[key] = value.strip()
    return metadata
