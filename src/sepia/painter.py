"""Paint pictures: a free web API first, the local GPU model when the API fails."""

import io
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from PIL import Image, UnidentifiedImageError

DEFAULT_IMAGE_MODEL = "black-forest-labs/FLUX.2-klein-4B"
"""The local model: Apache 2.0, four steps, image editing built in."""
MODEL_FILES = [
    "model_index.json",
    "scheduler/*",
    "text_encoder/*",
    "tokenizer/*",
    "transformer/*",
    "vae/*",
]
"""What the diffusers pipeline needs; skips the 7.8 GB single-file checkpoint."""
STEPS = 4
"""FLUX.2 [klein] is distilled to finish an image in four steps."""
GUIDANCE = 1.0
"""Distilled models are trained for CFG 1.0; higher values oversaturate."""
PIXELS = 1024 * 640
"""Target image area for the API; the symbol grid needs less, so more costs time."""
LOCAL_PIXELS = 768 * 512
"""Largest area the local model paints. Above it an 8 GB card spills into shared
memory and a 3 second picture takes a minute."""
LOCAL_EDIT_PIXELS = 640 * 416
"""Editing also holds the reference picture, so it gets a smaller budget."""

KEYLESS_URL = "https://image.pollinations.ai/prompt/"
"""Pollinations' anonymous endpoint: about one image per 15 seconds, with a logo."""
KEYED_URL = "https://gen.pollinations.ai/image/"
"""Pollinations' current endpoint; needs a key from enter.pollinations.ai."""
DEFAULT_API_MODEL = "black-forest-labs/flux.2-klein-4b"
API_TIMEOUT_SECONDS = 90
COOLDOWN_SECONDS = 120
"""After the API says "too many requests", go straight to the local model this long."""

Device = Literal["cuda", "mps", "cpu"]
Source = Literal["api", "local"]


class PainterError(RuntimeError):
    """A picture could not be painted."""

    def __init__(self, message: str, *, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited


@dataclass(frozen=True)
class Painting:
    image: Image.Image
    source: Source
    seconds: float


class Painter(Protocol):
    def paint(
        self,
        prompt: str,
        size: tuple[int, int],
        seed: int,
        reference: Image.Image | None = None,
    ) -> Painting: ...


def image_size(aspect: float, pixels: int = PIXELS) -> tuple[int, int]:
    """Width and height near `pixels` in area with the given width/height ratio.

    Both sides are multiples of 16, which the model's latent grid requires.
    """
    height = (pixels / aspect) ** 0.5
    width = height * aspect
    return max(16, round(width / 16) * 16), max(16, round(height / 16) * 16)


class ApiPainter:
    """Paints through Pollinations.

    The API cannot see the previous picture, so an edit is repainted from the full
    prompt with the scene's fixed seed, which keeps the composition close.
    """

    def __init__(self, key: str | None = None, model: str = DEFAULT_API_MODEL) -> None:
        self._key = key
        self._model = model

    def paint(
        self,
        prompt: str,
        size: tuple[int, int],
        seed: int,
        reference: Image.Image | None = None,
    ) -> Painting:
        started = time.perf_counter()
        request = self.request(prompt, size, seed)
        try:
            with urllib.request.urlopen(request, timeout=API_TIMEOUT_SECONDS) as reply:
                kind = reply.headers.get_content_type()
                data = reply.read()
        except urllib.error.HTTPError as exc:
            limited = exc.code in (402, 429)
            message = f"image API: HTTP {exc.code}"
            raise PainterError(message, rate_limited=limited) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PainterError(f"image API unreachable: {exc}") from exc
        if not kind.startswith("image/"):
            raise PainterError(f"image API returned {kind}, not an image")
        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise PainterError("image API returned an unreadable image") from exc
        return Painting(image, "api", time.perf_counter() - started)

    def request(
        self, prompt: str, size: tuple[int, int], seed: int
    ) -> urllib.request.Request:
        width, height = size
        query: dict[str, str | int] = {"width": width, "height": height, "seed": seed}
        headers = {"User-Agent": "sepia-cli"}
        if self._key is None:
            base = KEYLESS_URL
            # private keeps prompts out of the public feed; enhance would rewrite them.
            query |= {"nologo": "true", "private": "true", "enhance": "false"}
        else:
            base = KEYED_URL
            query |= {"model": self._model}
            headers |= {"Authorization": f"Bearer {self._key}"}
        path = urllib.parse.quote(prompt, safe="")
        url = f"{base}{path}?{urllib.parse.urlencode(query)}"
        return urllib.request.Request(url, headers=headers)


LOCAL_MISSING = "local painting needs the extra: install sepia-cli[local]"


def local_installed() -> bool:
    """Whether the optional `local` extra (torch and diffusers) is installed."""
    import importlib.util

    return all(importlib.util.find_spec(name) for name in ("torch", "diffusers"))


def select_device() -> Device:
    """Fastest available device, in the order CUDA, then MPS, then CPU."""
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def local_model_ready(model_id: str = DEFAULT_IMAGE_MODEL) -> bool:
    """Whether the local model is already downloaded."""
    if not local_installed():
        return False
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        snapshot_download(model_id, allow_patterns=MODEL_FILES, local_files_only=True)
    except (LocalEntryNotFoundError, OSError):
        return False
    return True


def download_local_model(model_id: str = DEFAULT_IMAGE_MODEL) -> str:
    """Download the local model (about 16 GB) and return its folder."""
    if not local_installed():
        raise PainterError(LOCAL_MISSING)
    from huggingface_hub import snapshot_download

    return str(snapshot_download(model_id, allow_patterns=MODEL_FILES))


class LocalPainter:
    """FLUX.2 [klein] on this machine. Loads on first use; safe across threads."""

    def __init__(self, model_id: str = DEFAULT_IMAGE_MODEL) -> None:
        self.model_id = model_id
        self.device: Device | None = None
        self._pipe: Any = None  # diffusers ships without type information
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if not local_installed():
            raise PainterError(LOCAL_MISSING)
        with self._lock:
            if self._pipe is None:
                self._build()

    def paint(
        self,
        prompt: str,
        size: tuple[int, int],
        seed: int,
        reference: Image.Image | None = None,
    ) -> Painting:
        """Paint `prompt`; with `reference`, edit that image instead of a new one."""
        import torch

        self.load()
        budget = LOCAL_PIXELS if reference is None else LOCAL_EDIT_PIXELS
        width, height = size
        if width * height > budget:
            width, height = image_size(width / height, budget)
        started = time.perf_counter()
        options: dict[str, Any] = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_inference_steps": STEPS,
            "guidance_scale": GUIDANCE,
            "generator": torch.Generator(device="cpu").manual_seed(seed),
        }
        if reference is not None:
            options["image"] = [reference.convert("RGB")]
        with self._lock, torch.inference_mode():
            try:
                image = self._pipe(**options).images[0]
            except (RuntimeError, ValueError) as exc:
                raise PainterError(f"local model failed: {exc}") from exc
        return Painting(image, "local", time.perf_counter() - started)

    def _build(self) -> None:
        import torch
        from diffusers import Flux2KleinPipeline, PipelineQuantizationConfig
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError

        device = select_device()
        dtype = torch.bfloat16 if device != "cpu" else torch.float32
        try:
            path = snapshot_download(
                self.model_id, allow_patterns=MODEL_FILES, local_files_only=True
            )
        except LocalEntryNotFoundError as exc:
            message = "local model not downloaded; run `sepia --download`"
            raise PainterError(message) from exc
        options: dict[str, Any] = {"torch_dtype": dtype}
        if device == "cuda":
            # 4-bit weights keep the transformer and text encoder inside 8 GB.
            options["quantization_config"] = PipelineQuantizationConfig(
                quant_backend="bitsandbytes_4bit",
                quant_kwargs={
                    "load_in_4bit": True,
                    "bnb_4bit_quant_type": "nf4",
                    "bnb_4bit_compute_dtype": dtype,
                },
                components_to_quantize=["transformer", "text_encoder"],
            )
        try:
            pipe = Flux2KleinPipeline.from_pretrained(path, **options)
            pipe.to(device)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PainterError(f"could not load {self.model_id}: {exc}") from exc
        pipe.set_progress_bar_config(disable=True)
        self.device = device
        self._pipe = pipe


class FallbackPainter:
    """Tries `primary` first and falls back to `fallback` when it fails.

    After a rate-limit answer the primary is skipped for `cooldown` seconds, so a
    busy API does not add a failed round trip to every picture.
    """

    def __init__(
        self, primary: Painter, fallback: Painter, cooldown: float = COOLDOWN_SECONDS
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._cooldown = cooldown
        self._skip_until = 0.0
        self.last_error: PainterError | None = None

    def paint(
        self,
        prompt: str,
        size: tuple[int, int],
        seed: int,
        reference: Image.Image | None = None,
    ) -> Painting:
        if time.monotonic() >= self._skip_until:
            try:
                painting = self._primary.paint(prompt, size, seed, reference)
            except PainterError as exc:
                self.last_error = exc
                if exc.rate_limited:
                    self._skip_until = time.monotonic() + self._cooldown
            else:
                self.last_error = None
                return painting
        return self._fallback.paint(prompt, size, seed, reference)


def build_painter(
    pollinations_key: str | None, model_id: str = DEFAULT_IMAGE_MODEL
) -> tuple[FallbackPainter, LocalPainter]:
    """The painting chain: keyed API, then keyless API, then the local model.

    A keyed request that runs out of free credit falls back to the keyless endpoint
    before the GPU is ever touched. The local painter is returned too, so callers can
    report or warm it up.
    """
    local = LocalPainter(model_id)
    chain = FallbackPainter(ApiPainter(), local)
    if pollinations_key:
        chain = FallbackPainter(ApiPainter(pollinations_key), chain)
    return chain, local
