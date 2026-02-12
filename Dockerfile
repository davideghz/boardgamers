FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    libpq-dev \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal
ENV GDAL_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu
ENV GEOS_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu

COPY requirements.txt .

RUN apt-get update && apt-get install -y gettext
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

COPY . .
