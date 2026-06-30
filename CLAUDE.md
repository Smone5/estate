# Estate Agent — Deployment Notes

## Backend vs frontend are deployed completely separately

- **Backend** (`backend/`) runs in the `app` Docker service. Code is NOT volume-mounted — any change requires:
  ```
  docker compose build app && docker compose up -d app
  ```

- **Frontend** (`frontend/`) is NOT a Docker service. `nginx` serves the static, pre-built
  `frontend/dist/` folder directly as a read-only volume mount (see `docker-compose.yml`,
  the `nginx` service `volumes: ./frontend/dist:/usr/share/nginx/html:ro`). Editing `.jsx`/`.css`
  files does nothing in the browser until you actually build:
  ```
  cd frontend && npm run build
  ```
  Then (usually not even required, since the volume is live-mounted, but safe to do):
  ```
  docker compose restart nginx
  ```

**Rule of thumb:** if you edited anything under `frontend/src`, you must run `npm run build`
in `frontend/` before the change is visible — rebuilding the `app` container does not touch it.
If a UI change "isn't showing up" after a backend rebuild, check `frontend/dist` mtime first.
