Development mode (hot reload):

docker compose --profile dev up


Uses llm-api-dev

Mounts your local folder

Auto reloads on save

Production mode (baked, stable):

docker compose --profile prod up --build -d