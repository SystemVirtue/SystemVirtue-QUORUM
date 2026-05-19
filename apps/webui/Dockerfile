FROM python:3.12-slim
WORKDIR /app
COPY index.html /app/index.html
RUN python - <<'PY'
from pathlib import Path
Path('/app/server.py').write_text('from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler\\nThreadingHTTPServer((\"0.0.0.0\", 8080), SimpleHTTPRequestHandler).serve_forever()\\n')
PY
EXPOSE 8080
CMD ["python", "/app/server.py"]
