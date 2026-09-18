# ----------------------------------------------------------------------------
# Local model discovery
#
# Scans models/ for GGUF files and complete Transformers model folders.
# Reads filenames and JSON metadata without loading model weights into RAM.
# Uses stable relative paths for local aliases and verifies available shards.
# Shares discovery results between the CLI, browser backend, and local service.
# ----------------------------------------------------------------------------

import json
import os
import re
from pathlib import Path

## Resolve models/ relative to the repository, regardless of the shell folder.
BASE_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = BASE_DIR / 'models'
LOCAL_URL = os.getenv('HAZAR_LOCAL_URL', 'http://127.0.0.1:8000/v1/chat/completions')

## Recognize the default local alias and exact model IDs from the scanner.
def isLocal(name):
    return name == 'local' or name.startswith('local:')

## Discover supported models using directory entries and lightweight metadata only.
def scanModels(root=None):
    ## Filenames and full relative directory names form stable, collision-free aliases.
    ## Never load tensors during discovery. Symlinks outside models/ are excluded.
    root = Path(root or MODEL_DIR).resolve()
    result = []
    if not root.is_dir(): return result
    for path in sorted(root.rglob('*'), key=lambda p: p.as_posix().casefold()):
        if not path.resolve().is_relative_to(root): continue

        ## GGUF
        if path.is_file() and path.suffix.lower() == '.gguf':

            ## A split GGUF is one model; llama.cpp reads the remaining shards.
            split = re.search(r'-(\d{5})-of-(\d{5})\.gguf$', path.name, re.I)
            if split:
                if int(split[1]) != 1: continue
                prefix = path.name[:split.start()]
                if any(not (path.parent / f'{prefix}-{i:05d}-of-{int(split[2]):05d}.gguf').is_file()
                       for i in range(1, int(split[2]) + 1)): continue
            backend = 'gguf'

        ## TransformersL
        elif path.is_dir() and (path / 'config.json').is_file():
            ## Transformers needs a complete save_pretrained directory, not bare weights.
            if not any(path.glob('*.safetensors')) and not any(path.glob('pytorch_model*.bin')): continue
            if not any((path / name).is_file() for name in
                       ('tokenizer.json', 'tokenizer.model', 'vocab.json', 'vocab.txt', 'spiece.model')): continue
            try: config = json.loads((path / 'config.json').read_text(encoding='utf-8'))
            except (OSError, ValueError): continue
            ## Quantized GPTQ/AWQ and other specialized loaders need separate backends.
            if config.get('quantization_config') or config.get('is_encoder_decoder'): continue
            ## Require every weight shard referenced by a Transformers index.
            complete = True
            for index in path.glob('*.index.json'):
                try:
                    shards = json.loads(index.read_text(encoding='utf-8')).get('weight_map', {}).values()
                    if any(not (path / shard).resolve().is_relative_to(root) or not (path / shard).is_file()
                           for shard in shards): complete = False
                except (OSError, ValueError, TypeError): complete = False
            if not complete: continue
            backend = 'transformers'
        else: continue
        ## Keep nested paths and extensions so similarly named models remain distinct.
        relative = path.relative_to(root).as_posix()
        result.append({'id': 'local:' + relative, 'name': relative, 'format': backend,
                       'path': str(path.resolve())})
    return result

def resolveModel(name, root=None):
    # ---------------------------------------------------------------------------
    # Rescan before inference so added or removed models take effect immediately.
    # The plain local alias selects the first discovered model.
    # Exact model IDs select their corresponding files or folders.
    # ---------------------------------------------------------------------------
    models = scanModels(root)
    if name == "local" and models: return models[0] 
    for model in models:
        if name == model["id"]: return model
    raise ValueError(f"Local model {name!r} not found. Run query.py --list-models.")

## Browser and gateway listings receive model choices without absolute disk paths.
def publicModels():
    return [{k: v for k, v in model.items() if k != 'path'} for model in scanModels()]
