# Use a lightweight Python 3.9 image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    libgl1 \
    libglew-dev \
    libglfw3 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set env variable for rendering
ENV MUJOCO_GL=egl

# Upgrade pip and install core Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY external/tonic /tonic
WORKDIR /tonic
COPY external/tonic/setup.py ./setup.py
RUN python3 setup.py install

WORKDIR /app
COPY . /app

CMD ["python3"]
