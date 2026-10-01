"""Local CLIP embeddings for representative frames and search text."""

from functools import lru_cache
from pathlib import Path
from threading import Lock

from prism.config import get_settings

MODEL_REPO = "sentence-transformers/clip-ViT-B-32"
MODEL_REVISION = "dbd2f229c483b7806e8067631d89cb9ca5287f2a"
MODEL_LOCK = Lock()


@lru_cache(maxsize=1)
def load_visual_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        MODEL_REPO,
        revision=MODEL_REVISION,
        device="cpu",
        local_files_only=True,
        cache_folder=str(get_settings().storage_path / "models"),
    )


def download_visual_model() -> None:
    from sentence_transformers import SentenceTransformer

    SentenceTransformer(
        MODEL_REPO,
        revision=MODEL_REVISION,
        device="cpu",
        cache_folder=str(get_settings().storage_path / "models"),
    )


def embed_frames(paths: list[Path]):
    from PIL import Image

    model = load_visual_model()
    for start in range(0, len(paths), 8):
        images = []
        try:
            for path in paths[start : start + 8]:
                with Image.open(path) as image:
                    images.append(image.convert("RGB"))
            vectors = model.encode(
                images, batch_size=8, normalize_embeddings=True, convert_to_numpy=True
            )
            yield from vectors
        finally:
            for image in images:
                image.close()


def embed_query(query: str):
    return load_visual_model().encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]
