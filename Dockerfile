# Lambda container image for LSAC Status Checker with Playwright
# Using Python 3.12 which is based on Amazon Linux 2023 with GLIBC 2.34 (required for Playwright)
FROM public.ecr.aws/lambda/python:3.12

# Install system dependencies for Playwright/Chromium
# Note: AL2023 uses dnf instead of yum
RUN dnf install -y \
    atk \
    cups-libs \
    gtk3 \
    libXcomposite \
    alsa-lib \
    libXcursor \
    libXdamage \
    libXext \
    libXi \
    libXrandr \
    libXScrnSaver \
    libXtst \
    pango \
    at-spi2-atk \
    libXt \
    xorg-x11-server-Xvfb \
    xorg-x11-xauth \
    dbus-glib \
    dbus-glib-devel \
    nss \
    mesa-libgbm \
    && dnf clean all

# Copy requirements and install Python dependencies
COPY requirements-lambda.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements-lambda.txt

# Install Playwright and Chromium
# Set PLAYWRIGHT_BROWSERS_PATH to install in a fixed location that Lambda can access
ENV PLAYWRIGHT_BROWSERS_PATH=/var/task/.playwright
RUN pip install playwright && \
    playwright install chromium && \
    chmod -R 755 /var/task/.playwright

# Copy application code
COPY lsac_checker.py ${LAMBDA_TASK_ROOT}/
COPY lambda_handler.py ${LAMBDA_TASK_ROOT}/

# Note: schools.txt is loaded from S3 at runtime via SCHOOLS_FILE env var
# Local testing can still use a local schools.txt file

# Set the handler
CMD ["lambda_handler.lambda_handler"]
