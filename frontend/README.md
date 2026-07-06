# madosho frontend

## Dev
`npm run dev` (proxies API to control :8000 / query :8001) -- backends must be running.

## Test
`npm test` -- Vitest component tests.

## E2E (integration-tier; needs the full stack)
1. From repo root: `docker compose up -d --build` (builds backend, pulls models -- slow first run).
2. `cd frontend && npx playwright install --with-deps chromium`
3. `MADOSHO_UI_URL=http://127.0.0.1:8080 npm run e2e`
4. Teardown: `docker compose down -v`
