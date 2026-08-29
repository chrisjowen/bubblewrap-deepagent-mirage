FROM public.ecr.aws/lts/ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates fuse \
      python3 python3-pip python3-venv \
      util-linux build-essential \
      libjpeg-dev zlib1g-dev libpng-dev libfreetype6-dev \
      libxml2-dev libxslt1-dev libssl-dev libffi-dev \
      libmupdf-dev mupdf-tools \
      poppler-utils tesseract-ocr \
      git \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# mountpoint-s3 (arch-aware)
RUN ARCH=$(uname -m) \
 && case "$ARCH" in \
      x86_64)  MS_ARCH=x86_64 ;; \
      aarch64) MS_ARCH=arm64  ;; \
      *) echo "unsupported arch: $ARCH" && exit 1 ;; \
    esac \
 && curl -fsSL -o /tmp/mount-s3.deb "https://s3.amazonaws.com/mountpoint-s3-release/latest/${MS_ARCH}/mount-s3.deb" \
 && dpkg -i /tmp/mount-s3.deb \
 && rm /tmp/mount-s3.deb

# Isolated venv so pip install works without PEP 668 tripping.
# Prepend venv bin to PATH; make `python` an alias for the venv python.
ENV VENV=/opt/venv
RUN python3 -m venv $VENV \
 && ln -sf $VENV/bin/python $VENV/bin/python3 \
 && ln -sf $VENV/bin/python /usr/local/bin/python
ENV PATH="$VENV/bin:$PATH"

# Pre-install the AgentCore CodeInterpreter library set + a few extras
# useful for document / data workflows.
RUN pip install --upgrade pip setuptools wheel \
 && pip install \
      numpy pandas scipy scikit-learn statsmodels \
      matplotlib seaborn plotly \
      pillow \
      openpyxl xlsxwriter xlrd \
      pypdf pdfplumber pymupdf reportlab \
      python-docx python-pptx \
      sympy mpmath \
      tqdm python-dateutil pytz \
      requests httpx beautifulsoup4 lxml \
      ipython jupyter-client \
      boto3 botocore

WORKDIR /workspace

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sleep", "infinity"]
