# syntax=docker/dockerfile:1
FROM python:3.13-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models

# tesseract = the default OCR engine for scanned documents (parser option
# ocr: true). The Debian package brings the binary + English traineddata
# (~30MB); other languages are apt packages (e.g. tesseract-ocr-fra).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (cached layer), then the project.
# server = FastAPI/SQLAlchemy/procrastinate; local = docling parser + granite
# embedder (+ lancedb); qdrant = the qdrant-client the default service store needs;
# container = docker-py, needed by the worker when compose.container.yaml opts a
# queue into per-job containers (all roles share this one image).
COPY pyproject.toml README.md ./
COPY backend ./backend
COPY madosho_cli ./madosho_cli
COPY madosho_mcp ./madosho_mcp
COPY madosho_toolserver ./madosho_toolserver
COPY research_agent ./research_agent
# PIP_EXTRAS lets overlays widen the install without a second Dockerfile --
# e.g. compose.ocr.yaml passes "ocr-easyocr" to add the easyocr engine.
ARG PIP_EXTRAS=""
RUN pip install ".[server,local,qdrant,container]" \
    && if [ -n "$PIP_EXTRAS" ]; then pip install ".[$PIP_EXTRAS]"; fi \
    # watchfiles powers the dev hot-reload loop: compose.override.yaml wraps each
    # service command in `watchfiles` so a bind-mounted code change restarts the
    # process instead of needing an image rebuild. Tiny + unused in deploy.
    && pip install watchfiles \
    # docling's tableformer pulls opencv-python, whose default build links GUI/X11
    # libs (libxcb.so.1, libGL.so.1) that slim-trixie omits. Swap in the headless
    # build: identical cv2 API, no GUI/system-lib deps — the right choice for a
    # server. (rapidocr still resolves cv2 from the headless package.)
    && pip uninstall -y opencv-python \
    && pip install opencv-python-headless

# All three roles run from this one image; compose overrides the command.
CMD ["madosho-server"]
