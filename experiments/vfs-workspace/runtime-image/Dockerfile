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

# Isolated venv at /opt/venv. Prepend to PATH so `python` and `pip` come
# from the venv. Also symlink /usr/local/bin/python for good measure.
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV \
 && ln -sf $VIRTUAL_ENV/bin/python /usr/local/bin/python \
 && ln -sf $VIRTUAL_ENV/bin/python3 /usr/local/bin/python3
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Pre-install the AgentCore CodeInterpreter library set + a few extras.
# Use explicit venv paths so this doesn't rely on PATH resolution during
# the RUN (belt-and-braces).
RUN /opt/venv/bin/pip install --upgrade pip setuptools wheel \
 && /opt/venv/bin/pip install \
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
