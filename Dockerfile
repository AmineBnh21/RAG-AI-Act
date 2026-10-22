# Image pour Hugging Face Spaces (SDK Docker) : Streamlit sur le port 7860, CPU uniquement.
# Le modèle d'embedding est téléchargé à la construction pour un démarrage sans réseau vers le Hub.
FROM python:3.11-slim

ARG EMBEDDING_MODEL=BAAI/bge-m3

# Spaces exécute le conteneur avec l'utilisateur 1000 : tout ce qui suit lui appartient,
# ce qui évite un « chown -R » qui dupliquerait le modèle dans une nouvelle couche.
RUN useradd -m -u 1000 user
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/user/.cache/huggingface \
    EMBEDDING_MODEL=${EMBEDDING_MODEL}
WORKDIR /app

# torch CPU d'abord : sinon sentence-transformers tire la version CUDA (plusieurs Go)
COPY requirements.txt .
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install -r requirements.txt

USER user
# Poids au format safetensors uniquement (le dépôt contient aussi pytorch_model.bin et ONNX, ~2 Go chacun)
RUN python -c "from huggingface_hub import snapshot_download; \
snapshot_download('${EMBEDDING_MODEL}', ignore_patterns=['*.bin', '*.onnx', 'onnx/*', '*.h5', '*.msgpack', '*.ot', 'imgs/*'])" \
    && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

COPY --chown=user:user . .

# Plus aucun accès au Hub à l'exécution : le modèle est dans l'image
ENV HF_HUB_OFFLINE=1
EXPOSE 7860
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true"]
