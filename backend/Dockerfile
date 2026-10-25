# 1. Start from a small official Python image
FROM python:3.11-slim

# 2. All following commands run inside this folder
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EMBED_CACHE_DIR=/opt/models

# 3. Copy ONLY requirements first - this makes rebuilds much faster
COPY requirements.txt .

# 4. Install the Python packages
RUN pip install --no-cache-dir -r requirements.txt

# 4b. Bake the embedding model into the image so the first upload is fast
#     and the container never needs to download it at run time (~130 MB)
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/models')"

# 5. Now copy the rest of the source code
COPY . .

# 6. Document which port the app listens on
EXPOSE 8000

# 7. The command that starts the app when the container runs (0.0.0.0 is not optional)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
