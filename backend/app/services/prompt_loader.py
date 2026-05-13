from pathlib import Path

ROOT = Path("/app")
LOCAL_ROOT = Path(__file__).resolve().parents[3]


def _base() -> Path:
    return ROOT if ROOT.exists() and (ROOT / "agents").exists() else LOCAL_ROOT


def read_text(path: str) -> str:
    file_path = _base() / path
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8")


def knowledge_context(*names: str) -> str:
    chunks: list[str] = []
    for name in names:
        text = read_text(f"knowledge_base/{name}")
        if text:
            chunks.append(f"\n\n## {name}\n{text}")
    return "\n".join(chunks)
