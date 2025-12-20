# Multi-language Dockerfile for QuillWorks Railway Service
# Supports: Python, PHP, Node.js, Rust, Go, and Android

FROM python:3.13-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive
ENV RUSTUP_HOME=/usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
ENV GOROOT=/usr/local/go
ENV GOPATH=/go
ENV ANDROID_HOME=/opt/android-sdk
ENV ANDROID_SDK_ROOT=/opt/android-sdk
ENV JAVA_HOME=/usr/lib/jvm/default-java
ENV PATH=/usr/local/cargo/bin:/usr/local/go/bin:/go/bin:${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/build-tools/34.0.0:$PATH

# Install system dependencies, Node.js, PHP, and Rust
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build essentials
    build-essential \
    gcc \
    g++ \
    # For WeasyPrint/PDF generation (WeasyPrint 67.0 requires these)
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    libffi-dev \
    shared-mime-info \
    libcairo2 \
    libcairo2-dev \
    libgirepository1.0-dev \
    gir1.2-pango-1.0 \
    # For image processing
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    # For pdf2image
    poppler-utils \
    # Networking tools
    curl \
    wget \
    # Git for some npm packages
    git \
    # PHP and Composer
    php \
    php-cli \
    php-common \
    php-mbstring \
    php-xml \
    php-curl \
    php-zip \
    php-mysql \
    php-sqlite3 \
    composer \
    # SSL for Rust
    libssl-dev \
    pkg-config \
    # Java for Android development (use default-jdk-headless for Debian Trixie compatibility)
    default-jdk-headless \
    # Unzip for Android SDK
    unzip \
    # Clean up
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (LTS version)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal \
    && rustup --version \
    && cargo --version \
    && rustc --version

# Install Go (latest stable)
RUN curl -fsSL https://go.dev/dl/go1.22.4.linux-amd64.tar.gz -o /tmp/go.tar.gz \
    && tar -C /usr/local -xzf /tmp/go.tar.gz \
    && rm /tmp/go.tar.gz \
    && mkdir -p /go/bin /go/src /go/pkg \
    && go version

# Install Android SDK command-line tools
RUN mkdir -p ${ANDROID_HOME}/cmdline-tools \
    && curl -fsSL https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -o /tmp/cmdline-tools.zip \
    && unzip -q /tmp/cmdline-tools.zip -d ${ANDROID_HOME}/cmdline-tools \
    && mv ${ANDROID_HOME}/cmdline-tools/cmdline-tools ${ANDROID_HOME}/cmdline-tools/latest \
    && rm /tmp/cmdline-tools.zip \
    && yes | ${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager --licenses || true \
    && ${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager "platform-tools" "build-tools;34.0.0" "platforms;android-34" \
    && chmod -R 755 ${ANDROID_HOME}

# Verify all installations
RUN echo "=== Installed Runtimes ===" && \
    python3 --version && \
    php --version | head -1 && \
    node --version && \
    npm --version && \
    composer --version | head -1 && \
    rustc --version && \
    cargo --version && \
    go version && \
    java -version 2>&1 | head -1 && \
    ${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager --version

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Wrangler CLI globally for Cloudflare Pages deployments
RUN npm install -g wrangler@latest

# Copy application code
COPY . .

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the application
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "600", "app:app"]
