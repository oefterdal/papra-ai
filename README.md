# Papra AI

FastAPI webhook service that enriches new Papra documents with an Ollama vision
model.

When Papra sends a `document:created` webhook, this service:

1. Accepts the webhook quickly and schedules enrichment as a FastAPI background
   task.
2. Fetches the document metadata, original file, and existing Papra tags.
3. Sends the file image, filename, existing extracted text, and available tags
   to Ollama.
4. Updates the document title and searchable content.
5. Reuses matching existing tags, or creates new tags when none fit.

The active prompt is stored in
`src/prompts/analysis.tmpl`.

## Configuration

Configuration is handled by `pydantic-settings`. Environment variables override
values from `.env`.

Create local config from the example:

```bash
cp .env.example .env
```

Variables:

- `PAPRA_BASE_URL`, default `http://papra:1221`
- `PAPRA_API_TOKEN`, required
- `PAPRA_WEBHOOK_SECRET`, required
- `OLLAMA_BASE_URL`, default `http://ollama:11434`
- `OLLAMA_MODEL`, default `minicpm-v:8b`
- `LOG_LEVEL`, default `INFO`
- `PAPRA_AI_TAG_COLOR`, default `#5B8DEF`
- `PAPRA_AI_ENV_FILE`, default `.env`

The Papra API token needs at least:

- `documents:read`
- `documents:update`
- `tags:read`
- `tags:create`

Logs are written to stdout for container collection. Set `LOG_LEVEL=DEBUG` for
more verbose runtime logging while diagnosing webhook or enrichment flow.

## Ollama

Pull a vision-capable model before processing documents:

```bash
ollama pull minicpm-v:8b
```

Then set `OLLAMA_MODEL` to the model name you want to use. Other vision-capable
Ollama models can be used as long as they support the `/api/generate` `images`
field.

Vision input is currently sent to Ollama for image files. PDFs and other
non-image files are enriched from the filename and Papra's existing extracted
content; scanned PDFs with little or no extracted text will need PDF rendering
support before the vision model can inspect their pages.

## Run Locally

```bash
uv run uvicorn main:app --app-dir src --host 0.0.0.0 --port 8000
```

## Development

Install the project dependencies with `uv`, then run the repository checks:

```bash
uv sync
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest
```

## Run With Docker

Build a local image:

```bash
docker build -t papra-ai:local .
```

Run it with your `.env` file:

```bash
docker run --rm \
  --env-file .env \
  -p 8000:8000 \
  papra-ai:local
```

If Papra and Ollama run in the same Docker network, set `PAPRA_BASE_URL` and
`OLLAMA_BASE_URL` to their service names, for example `http://papra:1221` and
`http://ollama:11434`.

## Deploy With Compose

Published images are intended to be pulled from GitHub Container Registry:

```yaml
services:
  papra-ai:
    image: ghcr.io/<github-owner>/papra-ai:latest
    container_name: papra-ai
    restart: unless-stopped
    env_file:
      - ./papra-ai/.env
    networks:
      - internal
    depends_on:
      - papra
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health")
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

Keep the webhook service on an internal Docker network unless you add an
external authentication layer. Papra can call it directly by service name:

```text
http://papra-ai:8000/webhook
```

For a stack where Ollama is also a Compose service on the same network, use:

```env
PAPRA_BASE_URL=http://papra:1221
OLLAMA_BASE_URL=http://ollama:11434
```

If Ollama runs outside Docker, set `OLLAMA_BASE_URL` to an address reachable
from the `papra-ai` container.

## Papra Webhook

Configure an organization webhook in Papra that listens for document creation
and points to:

```text
http://<service-host>:8000/webhook
```

If Papra SSRF protection blocks local/private webhook targets, allowlist the
service hostname in Papra's webhook configuration.

For an internal Compose deployment that means adding `papra-ai` to Papra's
allowed webhook hostnames:

```env
WEBHOOK_URL_ALLOWED_HOSTNAMES=papra-ai
```

Papra webhook requests must include the Standard Webhooks signature headers
produced by Papra. Set `PAPRA_WEBHOOK_SECRET` to the secret configured for the
Papra organization webhook; invalid or stale signed requests are rejected.

Webhook acceptance only means enrichment was scheduled. The current background
task runs inside the FastAPI process, so a container restart can interrupt work
that has already been accepted.

Accepted webhook IDs are deduplicated for five minutes inside the FastAPI
process. This prevents immediate delivery retries from scheduling duplicate
enrichment work, but the deduplication state is cleared on restart.

The service exposes a lightweight health endpoint for container probes:

```text
http://<service-host>:8000/health
```

## Publish Images

The repository includes `.github/workflows/publish-container.yml` for GHCR. It
builds `linux/amd64` and `linux/arm64` images:

- pushes to the default `main` branch publish `latest` and `main` tags
- tags like `v0.1.0` publish `0.1.0` and `0.1` tags
- manual workflow runs publish the metadata tags allowed by the workflow event

After pushing this repository to GitHub, make the GHCR package public if users
should pull without registry credentials.

Create a versioned release by pushing a version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Users can then pin a Compose deployment to a released image:

```yaml
image: ghcr.io/oefterdal/papra-ai:0.1.0
```

## Notes

Existing Papra tags are included in the prompt so the model can prefer them
before suggesting new tags.

## License

Papra AI is licensed under the GNU Affero General Public License v3.0. See
`LICENSE`.
