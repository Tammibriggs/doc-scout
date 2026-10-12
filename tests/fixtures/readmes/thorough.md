# Uptime

## Authentication

Send your API token in the `Authorization: Bearer <token>` header.

## Endpoints

### List checks

`GET /api/checks` returns every check you have created, newest first.

```bash
curl -H "Authorization: Bearer $TOKEN" https://uptime.example.com/api/checks
```

Response:

```json
[{"id": "c1", "url": "https://example.com"}]
```

Returns 200 on success, 401 if the token is missing.

### Create a check

`POST /api/checks` creates a new check for the given URL and starts monitoring it.

```bash
curl -X POST -d '{"url": "https://example.com"}' https://uptime.example.com/api/checks
```

```json
{"id": "c2", "url": "https://example.com"}
```

Returns 201 Created, or 400 if the URL is invalid.
