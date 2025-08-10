import os
import torch
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
from transformers import AutoTokenizer, AutoModelForCausalLM
import uvicorn

# 本地模型路径
MODEL_DIR = "/Users/hewenxin/mlx_models/qwen3_rerank_0.6"
HOST = os.getenv("RERANK_HOST", "0.0.0.0")
PORT = 7998
MAX_LENGTH = 32000

app = FastAPI()

# 加载模型和分词器
tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, padding_side="left")
model = AutoModelForCausalLM.from_pretrained(MODEL_DIR).eval()

# 定义前缀后缀和特殊token
prefix = "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n"
suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
prefix_tokens = tokenizer.encode(prefix, add_special_tokens=False)
suffix_tokens = tokenizer.encode(suffix, add_special_tokens=False)
token_false_id = tokenizer.convert_tokens_to_ids("no")
token_true_id = tokenizer.convert_tokens_to_ids("yes")

class RerankRequest(BaseModel):
    query: str
    documents: List[str]
    instruction: Optional[str] = None

class RerankResponse(BaseModel):
    scores: List[float]

def format_instruction(instruction: Optional[str], query: str, doc: str) -> str:
    instr = instruction or "Given a web search query, retrieve relevant passages that answer the query"
    return f"<Instruct>: {instr}\n<Query>: {query}\n<Document>: {doc}"

def process_inputs(pairs: List[str]):
    # combine prefix, text, and suffix at string level and tokenize with padding in one call
    texts = [prefix + text + suffix for text in pairs]
    inputs = tokenizer(
        texts,
        padding=True,
        truncation='longest_first',
        max_length=MAX_LENGTH,
        return_tensors='pt',
        add_special_tokens=False
    )
    return {k: v.to(model.device) for k, v in inputs.items()}

@torch.no_grad()
def compute_logits(inputs):
    logits = model(**inputs).logits[:, -1, :]
    true_vec = logits[:, token_true_id]
    false_vec = logits[:, token_false_id]
    scores = torch.nn.functional.log_softmax(torch.stack([false_vec, true_vec], dim=1), dim=1)[:, 1].exp().tolist()
    return scores

@app.post("/rerank", response_model=RerankResponse)
def rerank(req: RerankRequest):
    pairs = [format_instruction(req.instruction, req.query, doc) for doc in req.documents]
    inputs = process_inputs(pairs)
    scores = compute_logits(inputs)
    return RerankResponse(scores=scores)

if __name__ == "__main__":
    uvicorn.run("serve_reranker:app", host=HOST, port=PORT)