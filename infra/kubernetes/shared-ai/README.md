# Ollama compartido para IMI LEG

IMI LEG usa el servicio `ollama` del namespace `shared-ai`. La imagen está
fijada por digest porque `qwen3.6:35b` provoca errores CUDA durante el prefill
con Ollama 0.32.5. La versión validada en la RTX 5090 es Ollama 0.31.2.

## Aplicar el pin

```bash
microk8s kubectl -n shared-ai patch deployment ollama \
  --type strategic \
  --patch-file infra/kubernetes/shared-ai/ollama-image-pin.patch.yaml
microk8s kubectl -n shared-ai rollout status deployment/ollama --timeout=300s
```

Antes de aplicar, guardar el estado vigente:

```bash
backup_dir="/home/root-labia/imi-leg-rollbacks/ollama-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
microk8s kubectl -n shared-ai get deployment ollama -o yaml \
  > "$backup_dir/deployment-before.yaml"
```

No volver a `ollama/ollama:latest` sin repetir las pruebas de `/api/embed`,
`/api/chat` y la reformulación E2E desde IMI LEG.

## Verificación mínima

```bash
microk8s kubectl -n shared-ai exec deployment/ollama -- ollama --version
microk8s kubectl -n shared-ai exec deployment/ollama -- ollama list
microk8s kubectl -n shared-ai logs deployment/ollama --since=10m \
  | grep -E '/api/(embed|chat)|CUDA error|illegal memory'
```

El resultado esperado es Ollama `0.31.2`, respuestas HTTP 200 para embeddings y
generación, y ausencia de `CUDA error` o `illegal memory`.
