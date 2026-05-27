# abench/prompt.py
from __future__ import annotations


def compose(task: str, augmentation: str | None) -> str:
    task = task.strip()
    if augmentation and augmentation.strip():
        return f"{task}\n\n---\n\n{augmentation.strip()}"
    return task
