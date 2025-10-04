# DHL MCP Server

FastMCP 2.0 server that surfaces DHL parcel data to Model Context Protocol clients.

## Environment

Set the following variables so the server can authenticate with DHL:

```bash
export DHL_USERNAME="your-email@example.com"
export DHL_PASSWORD="your-password"
```

## Run locally

Install dependencies and start the MCP server directly:

```bash
python3 -m pip install fastmcp requests
fastmcp run dhl_mcp_server.py
```

## Docker

Build an image (tagged to match `gerbenvds/mcp-dhlecommerce:latest` in the example below):

```bash
docker build -t gerbenvds/mcp-dhlecommerce:latest .
```

Run it with credentials provided via environment variables—mirroring the MCP client configuration snippet:

```bash
docker run --rm \
  -e DHL_USERNAME=xyzzy \
  -e DHL_PASSWORD=hunter2 \
  -i gerbenvds/mcp-dhlecommerce:latest
```

When using the Model Context Protocol JSON configuration, point the `command` to `docker` and supply the same arguments.

## Automated image builds

GitHub Actions publishes container images to GitHub Container Registry at `ghcr.io/gerbenvds/mcp-dhlecommerce`.

- Pushes to `main` produce the `latest` tag and a commit-specific `sha-<shortsha>` tag.
- Tagging the repository with `v*` (for example `v0.3.0`) produces a semantic tag (`0.3.0`) alongside `latest` and embeds the same version in the server via `MCP_SERVER_VERSION`.
- Workflow file: `.github/workflows/docker.yml`.

## Resources

- `dhl://parcels` — Latest parcel payload from DHL.
- `dhl://parcels/{identifier}` — Parcel lookup by parcel ID or barcode.
- `dhl://user/profile` — Authenticated DHL account information.

## Tools

- `filter_parcels` — Filter parcels by status, category, recency, or returnability.
- `parcel_summary` — Get a concise status summary for a parcel.
