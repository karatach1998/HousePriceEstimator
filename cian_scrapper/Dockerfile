ARG PYTHON_VERSION=3.10

FROM python:${PYTHON_VERSION}-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    git \
    && rm -rf /var/lib/apt/lists/*
RUN curl -sSL https://install.python-poetry.org | POETRY_HOME=/usr python3 -

WORKDIR /app
COPY pyproject.toml poetry.lock /app/
RUN poetry install
COPY . .

CMD ["poetry", "run", "python", "cian_scrapper/cian_scrapper.py"]
