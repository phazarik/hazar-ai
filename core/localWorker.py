#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# Local model worker
#
# Loads one GGUF or Transformers causal language model from local files.
# Receives requests and returns completion events through JSON-line pipes.
# Validates finite context limits and reports backend token usage.
# Buffers GGUF replies for exact usage; Transformers replies stream as generated.
# Exits when the parent service unloads the model, releasing inference memory.
# ----------------------------------------------------------------------------

import json
import os
import sys
import threading

## Reserve stdout for IPC; native and Python loader messages go to stderr.
ipc = os.fdopen(os.dup(sys.stdout.fileno()), 'w', buffering=1, encoding='utf-8')
os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

## Flush one protocol event so the parent can forward it without pipe buffering.
def emit(value):
    ipc.write(json.dumps(value, ensure_ascii=False) + '\n')
    ipc.flush()

## Initialize the requested backend once, then accept successive completion requests.
def run():
    spec = json.loads(sys.argv[1])
    context = max(128, int(os.getenv('HAZAR_LOCAL_CONTEXT', '4096')))
    ## Import only the selected backend; unrelated model libraries stay out of RAM.
    if spec['format'] == 'gguf':
        from llama_cpp import Llama
        ## Memory-map GGUF weights and avoid pinning the complete model in RAM.
        model = Llama(model_path=spec['path'], n_ctx=context, use_mmap=True,
                      use_mlock=False, n_gpu_layers=int(os.getenv('HAZAR_GPU_LAYERS', '0')),
                      n_batch=min(256, context), verbose=False)
        ## Cap against the model's trained context unless the library lacks metadata.
        trained = [int(v) for k, v in model.metadata.items() if k.endswith('.context_length')]
        if trained: context = min(context, min(trained))
        ## Validate the template-rendered prompt before llama.cpp can clamp output.
        completion = model.create_completion
        ## This wrapper sees the chat-template prompt before llama.cpp generates tokens.
        def boundedCompletion(*args, **kwargs):
            prompt = kwargs.get('prompt', args[0] if args else '')
            tokens = prompt if isinstance(prompt, list) else model.tokenize(prompt.encode('utf-8'), special=True)
            available = context - len(tokens)
            if available < 1:
                raise ValueError(f'Prompt has {len(tokens)} tokens; context is {context}. Reduce attachments/history.')
            budget = kwargs.get('max_tokens')
            if budget and budget > available:
                raise ValueError(f'Only {available} output tokens fit in the {context}-token context.')
            kwargs['max_tokens'] = budget or min(900, available)
            return completion(*args, **kwargs)
        model.create_completion = boundedCompletion
        tokenizer = None
    else:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        ## Require local files and disable custom model-code downloads or execution.
        tokenizer = AutoTokenizer.from_pretrained(spec['path'], local_files_only=True,
                                                  trust_remote_code=False)
        model = AutoModelForCausalLM.from_pretrained(
            spec['path'], local_files_only=True, trust_remote_code=False,
            torch_dtype='auto', device_map=os.getenv('HAZAR_LOCAL_DEVICE', 'cpu'),
            low_cpu_mem_usage=True)
        model.eval()
        ## Cap the configured context against model and tokenizer metadata when available.
        trained = getattr(model.config, 'max_position_embeddings', None)
        if isinstance(trained, int) and trained > 0: context = min(context, trained)
        if 0 < tokenizer.model_max_length < 100000000: context = min(context, tokenizer.model_max_length)
    ## Signal readiness only after weights and context metadata are available.
    emit({'ready': True, 'contextLimit': context})
    ## EOF ends the worker; each input line is one complete inference request.
    for line in sys.stdin:
        try:
            payload = json.loads(line)
            ## An omitted output budget uses a bounded default, not unlimited generation.
            requested = payload.get('max_tokens')
            if requested is not None and (type(requested) is not int or requested < 1):
                raise ValueError('max_tokens must be a positive integer')
            if tokenizer is None:
                # ------------------------------------------------------------------------
                # llama.cpp applies the GGUF chat template and counts its complete prompt.
                # It rejects oversized prompts; no history is silently discarded.
                # Buffered GGUF generation returns exact backend usage, including
                # the rendered chat template. The service keeps SSE compatibility.
                # ------------------------------------------------------------------------
                result = model.create_chat_completion(
                    messages=payload['messages'], stream=False, max_tokens=requested,
                    temperature=float(payload.get('temperature', 0.7)))
                choice = result['choices'][0]
                emit({'model': spec['id'], 'contextLimit': context,
                      'choices': [{'delta': {'content': choice['message'].get('content', '')},
                                   'finish_reason': choice['finish_reason']}],
                      'usage': result['usage']})
            else:
                from transformers import TextIteratorStreamer
                ## Count the complete rendered prompt, including roles and special tokens.
                if tokenizer.chat_template:
                    inputs = tokenizer.apply_chat_template(payload['messages'], tokenize=True,
                        add_generation_prompt=True, return_tensors='pt', return_dict=True)
                else:
                    # Base and newly trained models may lack a chat template.
                    # This explicit text serialization permits inference, but does
                    # not make a base model instruction-tuned.
                    text = '\n\n'.join(m['role'].upper() + ':\n' + m['content']
                                       for m in payload['messages']) + '\n\nASSISTANT:\n'
                    inputs = tokenizer(text, return_tensors='pt')
                ## Reserve output space before moving prompt tensors to the model device.
                prompt = inputs['input_ids'].shape[-1]
                available = context - prompt
                if available < 1: raise ValueError(f'Prompt has {prompt} tokens; context is {context}. Reduce attachments/history.')
                if requested is not None and requested > available:
                    raise ValueError(f'Only {available} output tokens fit in the {context}-token context.')
                budget = requested or min(900, available)
                inputs = {k: v.to(model.device) for k, v in inputs.items()}
                ## Generate in a thread while the main loop forwards decoded text fragments.
                streamer = TextIteratorStreamer(tokenizer, skip_prompt=True,
                                                skip_special_tokens=True, timeout=1)
                output, errors = [], []
                ## Inference mode avoids training gradients and their memory allocations.
                def generate():
                    try:
                        with torch.inference_mode():
                            output.append(model.generate(**inputs, max_new_tokens=budget,
                                do_sample=False, streamer=streamer,
                                pad_token_id=(tokenizer.pad_token_id if tokenizer.pad_token_id is not None
                                              else tokenizer.eos_token_id)))
                    except BaseException as error:
                        errors.append(error)
                        streamer.end()
                thread = threading.Thread(target=generate, daemon=True)
                thread.start()
                ## A short timeout checks generation errors without hanging on a failed thread.
                import queue
                iterator = iter(streamer)
                while True:
                    try: text = next(iterator)
                    except StopIteration: break
                    except queue.Empty:
                        if errors: raise errors[0]
                        continue
                    if text: emit({'model': spec['id'], 'contextLimit': context,
                        'choices': [{'delta': {'content': text}, 'finish_reason': None}]})
                thread.join()
                if errors: raise errors[0]
                ## Count generated token IDs directly; report a cutoff distinctly from EOS.
                tokens = output[0][0, prompt:]
                count = len(tokens)
                eos = model.generation_config.eos_token_id
                eos = eos if isinstance(eos, list) else [eos]
                reason = 'stop' if int(tokens[-1]) in eos or count < budget else 'length'
                emit({'model': spec['id'], 'contextLimit': context,
                      'choices': [{'delta': {}, 'finish_reason': reason}],
                      'usage': {'prompt_tokens': prompt, 'completion_tokens': count,
                                'total_tokens': prompt + count}})
            ## Mark the request complete while keeping the loaded model for reuse.
            emit({'done': True})
        ## Return request failures through the protocol so the UI can restore the prompt.
        except Exception as error:
            emit({'error': {'message': str(error)}})
            emit({'done': True})

## Loader failures also use JSON events, then exit for cleanup by the parent.
if __name__ == '__main__':
    try: run()
    except Exception as error:
        emit({'error': {'message': f'Model load failed: {error}'}})
        sys.exit(1)
