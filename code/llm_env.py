"""Load local LLM settings without putting secrets in git.

Resolution order for api_key / base_url / model:
  CLI flag  >  <PROVIDER>_… env  >  built-in non-secret default

Put keys in a repo-root `.env` (gitignored). The file is loaded automatically.
Add a new vendor by defining NAME_API_KEY / NAME_BASE_URL / NAME_MODEL.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Public defaults only — never put API keys here.
BUILTIN: dict[str, dict[str, str]] = {
    "qwen": {
        "label": "千问 (Qwen)",
        "base_url": "https://token.pjlab.org.cn/v1",
        "model": "qwen3.5-397b",
        "response_format": "json_schema",
        "out_dir": "local_qwen35",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "response_format": "json_object",
        "out_dir": "local_deepseek",
    },
}

_SKIP_ENV_PREFIXES = {"MEM0_EMBED"}


def load_dotenv_files(*paths: Path) -> list[Path]:
    """Load KEY=VAL lines into os.environ. Existing env vars win."""
    loaded: list[Path] = []
    candidates = paths or (ROOT / ".env", ROOT / "code" / ".env")
    for path in candidates:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            if key:
                os.environ.setdefault(key, val)
        loaded.append(path)
    return loaded


def _prefix(name: str) -> str:
    return name.strip().upper().replace("-", "_")


def _env(prefix: str, suffix: str) -> str | None:
    val = os.environ.get(f"{prefix}_{suffix}")
    if val is None:
        return None
    val = val.strip()
    return val or None


def discover_providers() -> list[str]:
    names = set(BUILTIN)
    for key, val in os.environ.items():
        if not key.endswith("_API_KEY") or not (val or "").strip():
            continue
        prefix = key[: -len("_API_KEY")]
        if prefix in _SKIP_ENV_PREFIXES:
            continue
        names.add(prefix.lower().replace("_", "-"))
    default = (os.environ.get("DEFAULT_PROVIDER") or "").strip().lower()
    if default:
        names.add(default)
    return sorted(names)


def resolve_llm(
    provider: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    response_format: str | None = None,
    out_dir: str | None = None,
    runs_dir: Path | None = None,
) -> dict:
    name = (provider or "").strip().lower()
    if not name:
        raise SystemExit(
            "Missing provider. Pass --provider, or set DEFAULT_PROVIDER in .env."
        )
    prefix = _prefix(name)
    builtin = BUILTIN.get(name, {})

    key = (
        api_key
        or _env(prefix, "API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("API_KEY")
    )
    url = base_url or _env(prefix, "BASE_URL") or builtin.get("base_url")
    mdl = model or _env(prefix, "MODEL") or builtin.get("model")
    fmt = (
        response_format
        or _env(prefix, "RESPONSE_FORMAT")
        or builtin.get("response_format")
        or "json_object"
    )
    if not key:
        raise SystemExit(
            f"Missing API key for '{name}'. Set {prefix}_API_KEY in .env "
            f"(or OPENAI_API_KEY), or pass --api-key."
        )
    if not url:
        raise SystemExit(
            f"Missing base URL for '{name}'. Set {prefix}_BASE_URL in .env "
            f"or pass --base-url."
        )
    if not mdl:
        raise SystemExit(
            f"Missing model for '{name}'. Set {prefix}_MODEL in .env "
            f"or pass --model."
        )

    safe = name.replace("/", "-").replace(":", "-").replace(" ", "-")
    folder = builtin.get("out_dir") or f"local_{safe}"
    default_out = str((runs_dir or (ROOT / "data" / "PMBench" / "runs")) / folder)
    return {
        "name": name,
        "label": builtin.get("label") or name,
        "api_key": key,
        "base_url": url,
        "model": mdl,
        "response_format": fmt,
        "out_dir": out_dir or default_out,
    }


def format_provider_list() -> str:
    lines = ["Configured LLM providers (.env + built-in defaults):"]
    for name in discover_providers():
        prefix = _prefix(name)
        builtin = BUILTIN.get(name, {})
        has_key = bool(
            _env(prefix, "API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("API_KEY")
        )
        model = _env(prefix, "MODEL") or builtin.get("model") or "(set --model)"
        url = _env(prefix, "BASE_URL") or builtin.get("base_url") or "(set --base-url)"
        flag = "key=set" if has_key else "key=MISSING"
        lines.append(f"  {name:12}  {flag:11}  model={model}  base_url={url}")
    lines.append(
        "Add another vendor: NAME_API_KEY / NAME_BASE_URL / NAME_MODEL in .env, "
        "then --provider NAME."
    )
    return "\n".join(lines)
