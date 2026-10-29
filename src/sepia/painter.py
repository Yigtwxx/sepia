"""Paint pictures: a free web API first, the local GPU model when the API fails."""

import contextlib
import io
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from PIL import Image, UnidentifiedImageError

from sepia.reference import Reference

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
Source = Literal["api", "keyless", "local"]


class PainterError(RuntimeError):
    """A picture could not be painted."""

    def __init__(
        self, message: str, *, rate_limited: bool = False, out_of_credit: bool = False
    ) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited
        self.out_of_credit = out_of_credit
        """The account has no credit left, which waiting does not change."""


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
        likeness: Reference | None = None,
    ) -> Painting:
        """Paint `prompt`. `reference` is the picture to edit; `likeness` is a
        picture of the subject whose look the painting copies."""
        ...


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
    prompt with the scene's fixed seed, which keeps the composition close. A
    likeness is on the web already: the keyed endpoint fetches it by its link,
    while the keyless one ignores reference pictures.
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
        likeness: Reference | None = None,
    ) -> Painting:
        started = time.perf_counter()
        request = self.request(prompt, size, seed, likeness)
        try:
            with urllib.request.urlopen(request, timeout=API_TIMEOUT_SECONDS) as reply:
                kind = reply.headers.get_content_type()
                data = reply.read()
        except urllib.error.HTTPError as exc:
            message = f"image API: HTTP {exc.code}"
            raise PainterError(
                message, rate_limited=exc.code == 429, out_of_credit=exc.code == 402
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PainterError(f"image API unreachable: {exc}") from exc
        if not kind.startswith("image/"):
            raise PainterError(f"image API returned {kind}, not an image")
        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise PainterError("image API returned an unreadable image") from exc
        source: Source = "keyless" if self._key is None else "api"
        return Painting(image, source, time.perf_counter() - started)

    def request(
        self,
        prompt: str,
        size: tuple[int, int],
        seed: int,
        likeness: Reference | None = None,
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
            if likeness is not None:
                query["image"] = likeness.url
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

    def load_in_background(self) -> threading.Thread:
        """Start loading on a background thread, so the first picture does not
        wait for it. A failure is left for `paint` to report."""

        def load() -> None:
            with contextlib.suppress(PainterError):
                self.load()

        thread = threading.Thread(target=load, name="sepia-load", daemon=True)
        thread.start()
        return thread

    def paint(
        self,
        prompt: str,
        size: tuple[int, int],
        seed: int,
        reference: Image.Image | None = None,
        likeness: Reference | None = None,
    ) -> Painting:
        """Paint `prompt`; with `reference`, edit that image instead of a new one,
        and with `likeness`, copy the subject's look from that picture."""
        self.load()  # first: it explains a missing extra before torch is imported
        import torch

        sources = [reference] if reference is not None else []
        if likeness is not None:
            sources.append(likeness.image)
        budget = LOCAL_EDIT_PIXELS if sources else LOCAL_PIXELS
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
        if sources:
            options["image"] = [source.convert("RGB") for source in sources]
        with self._lock, torch.inference_mode():
            try:
                image = self._pipe(**options).images[0]
            except (RuntimeError, ValueError) as exc:
                raise PainterError(f"local model failed: {exc}") from exc
        return Painting(image, "local", time.perf_counter() - started)

    def _build(self) -> None:
        _quiet_libraries()  # first: torch logs a warning while it loads
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
        options: dict[str, Any] = {"dtype": dtype}
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


def _quiet_libraries() -> None:
    """Keep the model libraries' progress bars and notes out of the prompt window.

    Errors still raise; only their progress output and warnings are dropped.
    """
    import logging

    # Without triton (not built for Windows) torch warns that its flop counter,
    # which sepia never uses, cannot count triton kernels.
    logging.getLogger("torch.utils.flop_counter").setLevel(logging.ERROR)
    from diffusers.utils import logging as diffusers_logging
    from transformers.utils import logging as transformers_logging

    for library in (diffusers_logging, transformers_logging):
        library.set_verbosity_error()
        library.disable_progress_bar()


class FallbackPainter:
    """Tries `primary` first and falls back to `fallback` when it fails.

    After a rate-limit answer the primary is skipped for `cooldown` seconds, so a
    busy API does not add a failed round trip to every picture. After an
    out-of-credit answer it is skipped for the rest of the session, since waiting
    does not bring credit back.
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
        likeness: Reference | None = None,
    ) -> Painting:
        if time.monotonic() >= self._skip_until:
            try:
                painting = self._primary.paint(prompt, size, seed, reference, likeness)
            except PainterError as exc:
                self.last_error = exc
                if exc.out_of_credit:
                    self._skip_until = math.inf
                elif exc.rate_limited:
                    self._skip_until = time.monotonic() + self._cooldown
            else:
                self.last_error = None
                return painting
        return self._fallback.paint(prompt, size, seed, reference, likeness)


def build_painter(
    pollinations_key: str | None,
    model_id: str = DEFAULT_IMAGE_MODEL,
    prefer_local: bool | None = None,
) -> tuple[FallbackPainter, LocalPainter]:
    """The painting chain, best quality first.

    With the local model downloaded: keyed API, then the local GPU, then the keyless
    API. The keyed API and the local model run the same FLUX.2 [klein] 4B, while the
    keyless endpoint uses a weaker model and adds a logo, so it comes last. Without
    the local model: keyed API, then keyless API, then the local painter, which only
    explains how to install it. `prefer_local` defaults to whether the model is
    downloaded. The local painter is returned too, so callers can report on it.
    """
    local = LocalPainter(model_id)
    keyless = ApiPainter()
    if prefer_local is None:
        prefer_local = local_model_ready(model_id)
    rest = (
        FallbackPainter(local, keyless)
        if prefer_local
        else FallbackPainter(keyless, local)
    )
    if pollinations_key:
        return FallbackPainter(ApiPainter(pollinations_key), rest), local
    return rest, local
