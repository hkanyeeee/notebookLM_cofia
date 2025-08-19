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
PORT = 7997
MAX_LENGTH = 4096

app = FastAPI()

# 加载模型和分词器
# 设备选择：优先 CUDA，其次 Apple MPS，最后 CPU
if torch.cuda.is_available():
    DEVICE = torch.device("cuda")
# elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
#     DEVICE = torch.device("mps")
else:
    DEVICE = torch.device("cpu")

tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, padding_side="left")
# 在 MPS 上优先使用 float32 以避免数值不稳定（NaN/Inf）
model_dtype = (
    torch.float32 if DEVICE.type == "mps" else (torch.float16 if DEVICE.type == "cuda" else torch.float32)
)
model = AutoModelForCausalLM.from_pretrained(MODEL_DIR, torch_dtype=model_dtype)
model = model.to(DEVICE).eval()

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
    return {k: v.to(DEVICE) for k, v in inputs.items()}

@torch.no_grad()
def compute_logits(inputs):
    outputs = model(**inputs)
    logits = outputs.logits[:, -1, :].to(torch.float32)
    selected = torch.stack([logits[:, token_false_id], logits[:, token_true_id]], dim=1)
    probs = torch.softmax(selected, dim=1)[:, 1]
    probs = torch.nan_to_num(probs, nan=0.0, posinf=1.0, neginf=0.0).clamp(0.0, 1.0)
    return probs.tolist()

@app.post("/rerank", response_model=RerankResponse)
def rerank(req: RerankRequest):
    pairs = [format_instruction(req.instruction, req.query, doc) for doc in req.documents]
    inputs = process_inputs(pairs)
    scores = compute_logits(inputs)
    return RerankResponse(scores=scores)

# health check
@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("serve_reranker:app", host=HOST, port=PORT)