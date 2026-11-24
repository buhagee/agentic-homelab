# Testing Scripts

Smoke tests and verification scripts for qacey-platform.

## Smoke Tests

### smoke-test.sh
Comprehensive platform smoke test.

**What it tests:**
- Container health (all services running)
- HTTP endpoints (200 OK responses)
- Database connectivity
- Service-specific checks:
  - Immich: API ping
  - Vaultwarden: /alive endpoint
  - Traefik: dashboard
  - CrowdSec: LAPI health
  - Hermes: dashboard
  - Hermes Agent direct dashboard (Justin + Annique): HTTPS route authentication required
  - AdGuard: web UI
  - Ollama: local embedding model API (`/api/tags`, loopback port 11434)
  - OpenCode V2: HTTPS route responds with authentication required

**Usage:**
```bash
bash testing/smoke-test.sh
```

**Exit codes:**
- `0` — All tests passed
- `1` — One or more tests failed

**When to run:**
- After platform start
- After deployments
- After configuration changes
- Before production releases

**Output:**
```
✓ Container immich-server is healthy
✓ Immich API responding
...
All smoke tests passed!
```

### smoke-test-api.sh
API-specific smoke tests.

**What it tests:**
- API endpoints with authentication
- Response codes and content
- API key validation
- Rate limiting
- Error handling

**Usage:**
```bash
bash testing/smoke-test-api.sh
```

**Prerequisites:**
- `IMMICH_API_KEY` in `.env`
- Services running

**When to run:**
- After API changes
- After OAuth configuration
- Before API-dependent deployments

## Test Workflow

### After Platform Start
```bash
# 1. Start platform
bash start.sh

# 2. Wait for services to be ready (30-60s)
sleep 60

# 3. Run smoke tests
bash testing/smoke-test.sh

# 4. If tests pass, platform is ready
```

### After Deployment
```bash
# 1. Deploy changes
bash deploy/deploy-agent-config.sh

# 2. Restart affected services
docker restart hermes-justin

# 3. Run smoke tests
bash testing/smoke-test.sh

# 4. Verify specific service
curl -f https://photos.example.com/api/server/ping
```

### Continuous Integration
```bash
# Run in CI pipeline
bash testing/smoke-test.sh || exit 1
bash testing/smoke-test-api.sh || exit 1
```

## Test Coverage

### Services Tested
- ✅ Traefik (proxy)
- ✅ Immich (photos)
- ✅ Vaultwarden (vault)
- ✅ Hermes agents
- ✅ CrowdSec (IDS)
- ✅ AdGuard (DNS)
- ✅ Uptime Kuma (monitoring)

### Not Tested (Manual Verification)
- OAuth login flows (requires browser)
- Mobile app functionality
- File upload/download
- End-to-end workflows

## Troubleshooting

### Test fails: "Container not healthy"
```bash
# Check container status
docker ps -a

# Check container logs
docker logs <container-name>

# Restart container
docker restart <container-name>

# Re-run test
bash testing/smoke-test.sh
```

### Test fails: "HTTP 502 Bad Gateway"
```bash
# Check if service is starting
docker logs <service-container>

# Wait longer for service to start
sleep 30
bash testing/smoke-test.sh
```

### Test fails: "Connection refused"
```bash
# Check if Traefik is running
docker ps | grep traefik

# Check Traefik logs
docker logs traefik

# Check network connectivity
docker network inspect qacey-proxy
```

## Adding New Tests

To add a new test to smoke-test.sh:

1. Add a test function:
```bash
test_my_service() {
    if curl -sf https://myservice.example.com/health > /dev/null; then
        log_success "My service is healthy"
        return 0
    else
        log_error "My service is not responding"
        return 1
    fi
}
```

2. Call it in the main test sequence:
```bash
test_my_service || FAILED=1
```

## Notes

- Tests are non-destructive (read-only)
- Tests use curl with `-f` flag (fail on HTTP errors)
- Tests have timeouts (default 10s)
- Tests log to stdout (pipe to file if needed)
- Tests are idempotent (safe to run multiple times)
