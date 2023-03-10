ARG PYTHON_VERSION=3.10

FROM node:16 as st-ymap-component-frontend

WORKDIR /frontend
COPY web/utils/ymap_component/frontend/package*.json .
RUN npm install
COPY web/utils/ymap_component/frontend .
RUN npm run build

FROM node:16 as st-pills-frontend

WORKDIR /frontend
COPY web/utils/streamlit_pills/frontend/package*.json .
RUN npm install
COPY web/utils/streamlit_pills/frontend .
RUN npm run build

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
RUN ls -l /usr/bin/poetry ; sleep 5
RUN poetry install
COPY . .
COPY --from=st-ymap-component-frontend /frontend/build /app/web/utils/ymap_component/frontend/build
COPY --from=st-pills-frontend /frontend/build /app/web/utils/streamlit_pills/frontend/build

EXPOSE 80

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

CMD ["poetry", "run", "streamlit", "run", "/app/web/main.py", "--theme.base=light", "--theme.primaryColor=#81c44b", "--browser.gatherUsageStats=false", "--server.headless=true", "--server.port=80", "--server.address=0.0.0.0"]