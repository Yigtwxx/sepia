"""Paint pictures: Cloudflare's free tier first, the local GPU model when it fails."""

import base64
import contextlib
import io
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
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

CLOUDFLARE_URL = (
    "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
)
CLOUDFLARE_MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
"""The local model's FLUX.2 [klein] 4B on Workers AI: about 100 pictures a day fit in
the free 10,000 neurons."""
API_SIDES = (256, 1920)
"""The smallest and largest width or height Workers AI paints."""
INPUT_SIDE = 512
"""Workers AI takes input pictures up to 512x512."""
USED_UP = 4006
"""Cloudflare's error code for a day's free neurons spent; they return at 00:00 UTC."""
API_TIMEOUT_SECONDS = 90
COOLDOWN_SECONDS = 120
"""After the API says "too many requests", go straight to the local model this long."""

Device = Literal["cuda", "mps", "cpu"]
Source = Literal["api", "local"]


class PainterError(RuntimeError):
    """A picture could not be painted."""

    def __init__(
        self, message: str, *, rate_limited: bool = False, out_of_credit: bool = False
    ) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited
        self.out_of_credit = out_of_credit
        """The free allocation is spent, which a short wait does not change."""


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


class CloudflarePainter:
    """Paints with FLUX.2 [klein] 4B on Cloudflare Workers AI.

    The picture to edit and the subject's picture go along as input pictures, so an
    edit works on the picture itself, as on the local model. Workers AI takes the
    request as multipart form data, even when there is only a prompt.
    """

    def __init__(
        self, account_id: str, token: str, model: str = CLOUDFLARE_MODEL
    ) -> None:
        self._account_id = account_id
        self._token = token
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
        request = self.request(prompt, size, seed, reference, likeness)
        try:
            with urllib.request.urlopen(request, timeout=API_TIMEOUT_SECONDS) as reply:
                data = reply.read()
        except urllib.error.HTTPError as exc:
            raise _api_error(exc) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PainterError(f"Cloudflare unreachable: {exc}") from exc
        try:
            encoded = json.loads(data)["result"]["image"]
            image = Image.open(io.BytesIO(base64.b64decode(encoded)))
            image.load()
        except (
            ValueError,
            KeyError,
            TypeError,
            UnidentifiedImageError,
            OSError,
        ) as exc:
            raise PainterError("Cloudflare returned no readable picture") from exc
        return Painting(image, "api", time.perf_counter() - started)

    def request(
        self,
        prompt: str,
        size: tuple[int, int],
        seed: int,
        reference: Image.Image | None = None,
        likeness: Reference | None = None,
    ) -> urllib.request.Request:
        low, high = API_SIDES
        width, height = (min(max(side, low), high) for side in size)
        fields = {
            "prompt": prompt,
            "width": str(width),
            "height": str(height),
            "seed": str(seed),
        }
        pictures = [reference] if reference is not None else []
        if likeness is not None:
            pictures.append(likeness.image)
        files = {
            f"input_image_{index}": _input_png(picture)
            for index, picture in enumerate(pictures)
        }
        body, kind = _multipart(fields, files)
        account = urllib.parse.quote(self._account_id, safe="")
        url = CLOUDFLARE_URL.format(account=account, model=self._model)
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": kind,
            "User-Agent": "sepia-cli",
        }
        return urllib.request.Request(url, data=body, headers=headers, method="POST")


def _api_error(exc: urllib.error.HTTPError) -> PainterError:
    """What a failed Workers AI call means for the painting chain. The reply's own
    text stays out of the message."""
    errors = _errors(exc)
    if any(code == USED_UP or "daily free allocation" in text for code, text in errors):
        message = "Cloudflare: today's free neurons are used up (back at 00:00 UTC)"
        return PainterError(message, out_of_credit=True)
    # Its safety filter flags some harmless pictures too, and not every time.
    if any("flagged" in text or "NSFW" in text for _, text in errors):
        return PainterError("Cloudflare's safety filter flagged the picture")
    if exc.code in (401, 403):
        return PainterError(f"Cloudflare rejected the API token (HTTP {exc.code})")
    return PainterError(f"Cloudflare: HTTP {exc.code}", rate_limited=exc.code == 429)


def _errors(exc: urllib.error.HTTPError) -> list[tuple[object, str]]:
    """Code and message of each error in a Workers AI error reply."""
    try:
        errors = json.loads(exc.read(65536))["errors"]
        return [
            (error.get("code"), str(error.get("message", "")))
            for error in errors
            if isinstance(error, dict)
        ]
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        return []


def _input_png(picture: Image.Image) -> bytes:
    """`picture` as PNG, shrunk to fit the input size Workers AI takes."""
    small = picture.convert("RGB")
    small.thumbnail((INPUT_SIDE, INPUT_SIDE))
    buffer = io.BytesIO()
    small.save(buffer, "PNG")
    return buffer.getvalue()


def _multipart(fields: dict[str, str], files: dict[str, bytes]) -> tuple[bytes, str]:
    """Form fields and PNG files as a multipart/form-data body, and its content type."""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
        parts.append(f"{head}{value}\r\n".encode())
    for name, data in files.items():
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{name}.png"\r\n'
            "Content-Type: image/png\r\n\r\n"
        )
        parts.append(head.encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


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

    try:
        return str(snapshot_download(model_id, allow_patterns=MODEL_FILES))
    except Exception as exc:  # the Hub's network, disk and HTTP errors alike
        name = type(exc).__name__
        raise PainterError(f"could not download {model_id} ({name})") from exc


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
            message = "local model not downloaded; type /local to download it"
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
    out-of-credit answer it is skipped for the rest of the session, since a short
    wait does not bring the free allocation back; `retry_primary` ends either.
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

    def retry_primary(self) -> None:
        """Try the primary again from the next picture on, ending a cooldown or an
        out-of-credit stop."""
        self._skip_until = 0.0


def build_painter(
    cloudflare: tuple[str, str] | None,
    model_id: str = DEFAULT_IMAGE_MODEL,
    local: LocalPainter | None = None,
) -> tuple[FallbackPainter | None, LocalPainter]:
    """The API chain and the local painter.

    The chain is Cloudflare, then the local model when Cloudflare fails. Both run
    FLUX.2 [klein] 4B, so a picture looks alike whichever paints it. Without
    Cloudflare's account ID and API token there is no chain (None) and only the
    local model paints; without the local model, its painter explains how to
    install it. A `local` painter given, perhaps with its model loaded, is kept.
    """
    local = local or LocalPainter(model_id)
    if cloudflare is None:
        return None, local
    account_id, token = cloudflare
    return FallbackPainter(CloudflarePainter(account_id, token), local), local
