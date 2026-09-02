"""Visual-tier IMAGE spike: voyage-multimodal-3.5 vs gemini-embedding-2.

Indexes every carousel slide (media_*.jpg) of the 19 image posts in the uiux
corpus with BOTH models into per-model sqlite-vec DBs:

  data/kb/visual-image-voyage.db  (voyage-multimodal-3.5, 1024-dim)
  data/kb/visual-image-gemini.db  (gemini-embedding-2,   3072-dim)

Index items are individual SLIDES, keyed "<post_id>:<slide_idx>". Retrieval is
cross-modal: a text question is embedded with the SAME model, matched against
slide vectors by cosine similarity, then deduped to POST level (a post counts
as retrieved if ANY of its slides hits; only its first/best occurrence is kept)
so metrics are comparable to the text tier via kb.eval.run_retrieval_eval.

Multimodal provider abstraction (shared with kb.visual_video):
  name / model / dims
  embed_images(images) -> list[vec]        # document side
  embed_query(text) -> vec                 # query side (same model)

Voyage inputs are PIL.Image via Client.multimodal_embed; Gemini inputs are raw
JPEG bytes via Part.from_bytes. Gemini free-tier quota is constrained, so
document embedding is batched (25 images/request) with retry/backoff.

Gold questions (30) were authored against the actual slide contents (each post's
lead slide was visually inspected) plus the per-post analysis text in
data/kb/kb-posts-all.json. Ground truth = post shortcode (aliased at eval).

Usage:
  uv run python -m kb.visual_image --index        # build both DBs (skips existing)
  uv run python -m kb.visual_image --gold         # write the gold set JSON
  uv run python -m kb.visual_image --eval         # run spike eval + report
  uv run python -m kb.visual_image --retrieve "question"
  uv run python -m kb.visual_image --all          # index + gold + eval
"""
from __future__ import annotations

import argparse
import json
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os  # noqa: E402  (after load_dotenv)

REPO_ROOT = Path(__file__).resolve().parent.parent
MEDIA_ROOT = Path("C:/Users/evano/repos/scrape-ig-saved-list/data/uiux")
DB_DIR = REPO_ROOT / "data" / "kb"
GOLD_PATH = REPO_ROOT / "data" / "eval" / "gold-set-visual-image.json"
RUNS_DIR = REPO_ROOT / "data" / "eval" / "runs"

MAX_IMAGE_SIDE = 1024  # downscale slides before embedding
VOYAGE_BATCH = 16
GEMINI_BATCH = 25  # batch to protect constrained free-tier quota
MAX_RETRIES = 6

# Cost model (verified vendor pricing, 2026-09-02; USD):
# - voyage-multimodal-3.5: billed PER PIXEL, $0.60 per 1 BILLION input pixels
#   (docs.voyageai.com/docs/pricing). Images <50k px are upscaled and charged
#   as 50k px ($0.00003 min/image); images >2M px are downsampled and charged
#   as 2M px ($0.0012 max/image). Per-image range: $0.00003-$0.0012.
# - gemini-embedding-2: billed per input token (ai.google.dev pricing). For a
#   reconcilable per-image figure we use the BATCH (paid-tier, 50% off) image
#   rate ~$0.00006/image (this spike actually ran on the free tier -> $0).
VOYAGE_USD_PER_1B_PIXELS = 0.60
VOYAGE_MIN_PIXELS_PER_IMAGE = 50_000
VOYAGE_MAX_PIXELS_PER_IMAGE = 2_000_000
GEMINI_BATCH = 1  # embed one image per request: multi-part contents yield a single joint embedding
GEMINI_USD_PER_IMAGE_BATCH = 0.00006  # batch/paid-tier image rate; standard tier ~2x



# ---------------------------------------------------------------------------
# Slide discovery


def discover_slides() -> list[dict]:
    """Enumerate every carousel slide (media_*.jpg) across the media root."""
    corpus = {str(r["post_id"]): r for r in _load_corpus()}
    items: list[dict] = []
    for cdir in sorted(MEDIA_ROOT.iterdir()):
        if not cdir.is_dir():
            continue
        for pdir in sorted(cdir.iterdir()):
            pid = pdir.name
            rec = corpus.get(pid)
            if rec is None:
                continue
            for i, img in enumerate(sorted(pdir.glob("media_*.jpg"))):
                items.append(
                    {
                        "item_id": f"{pid}:{i}",
                        "post_id": pid,
                        "shortcode": rec["shortcode"],
                        "slide_idx": i,
                        "path": img,
                    }
                )
    return items


def _load_corpus() -> list[dict]:
    from kb.consolidate import load_merged

    return load_merged()


# ---------------------------------------------------------------------------
# Providers


def _api_key(var: str) -> str:
    key = os.environ.get(var)
    if not key:
        raise RuntimeError(f"{var} not set; add it to the repo .env")
    return key


def _load_image(path: Path):
    from PIL import Image

    img = Image.open(path).convert("RGB")
    if max(img.size) > MAX_IMAGE_SIDE:
        scale = MAX_IMAGE_SIDE / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    return img


class VoyageImageProvider:
    """voyage-multimodal-3.5, 1024-dim; images in, text queries in."""

    name = "voyage"
    model = "voyage-multimodal-3.5"
    dims = 1024
    batch_size = VOYAGE_BATCH
    db_path = DB_DIR / "visual-image-voyage.db"

    def __init__(self) -> None:
        import voyageai

        self._client = voyageai.Client(api_key=_api_key("VOYAGE_API_KEY"))

    def embed_images(self, paths: list[Path]) -> list[list[float]]:
        imgs = [_load_image(p) for p in paths]
        out: list[list[float]] = []
        for i in range(0, len(imgs), self.batch_size):
            chunk = imgs[i : i + self.batch_size]
            resp = _with_retry(
                lambda: self._client.multimodal_embed(
                    inputs=[[im] for im in chunk], model=self.model, input_type="document"
                )
            )
            out.extend(list(e) for e in resp.embeddings)
            print(f"  [{self.name}] embedded {min(i + self.batch_size, len(imgs))}/{len(imgs)}")
        return out

    def embed_query(self, text: str) -> list[float]:
        resp = _with_retry(
            lambda: self._client.multimodal_embed(
                inputs=[[text]], model=self.model, input_type="query"
            )
        )
        return list(resp.embeddings[0])


class GeminiImageProvider:
    """gemini-embedding-2, 3072-dim; raw JPEG bytes via Part.from_bytes."""

    name = "gemini"
    model = "gemini-embedding-2"
    dims = 3072
    batch_size = GEMINI_BATCH
    db_path = DB_DIR / "visual-image-gemini.db"

    def __init__(self) -> None:
        from google import genai

        self._client = genai.Client(api_key=_api_key("GEMINI_API_KEY"))


    def embed_query(self, text: str) -> list[float]:
        resp = _with_retry(
            lambda: self._client.models.embed_content(model=self.model, contents=[text])
        )
        return list(resp.embeddings[0].values)




    def embed_images(self, paths: list[Path]) -> list[list[float]]:
        """One embed_content call per image: multi-part contents return a single
        joint embedding (not one per part), so batching would corrupt the index."""
        from google.genai import types

        out: list[list[float]] = []
        for i, p in enumerate(paths):
            part = types.Part.from_bytes(data=p.read_bytes(), mime_type="image/jpeg")
            resp = _with_retry(
                lambda: self._client.models.embed_content(model=self.model, contents=[part])
            )
            out.append(list(resp.embeddings[0].values))
            if (i + 1) % 25 == 0:
                print(f"  [{self.name}] embedded {i + 1}/{len(paths)}")
                time.sleep(2)  # be gentle with the constrained free tier
        print(f"  [{self.name}] embedded {len(paths)}/{len(paths)}")
        return out


PROVIDERS = {"voyage": VoyageImageProvider, "gemini": GeminiImageProvider}


def _with_retry(fn):
    """Retry an embed call with exponential backoff on rate/transient errors."""
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - provider errors are heterogeneous
            last = e
            wait = min(2**attempt * 2, 60)
            print(f"    embed error ({e}); retry {attempt + 1}/{MAX_RETRIES} in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"embedding failed after {MAX_RETRIES} retries: {last}")


def get_provider(name: str):
    return PROVIDERS[name]()


# ---------------------------------------------------------------------------
# Indexing (per-model sqlite-vec, vec0 virtual table)


def _connect(provider) -> "object":
    import sqlite3

    import sqlite_vec

    provider.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(provider.db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _ensure_schema(conn, provider) -> None:
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS visual_items USING vec0("
        f"  item_id TEXT PRIMARY KEY, embedding float[{provider.dims}]"
        f")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS items ("
        "  item_id TEXT PRIMARY KEY, post_id TEXT NOT NULL, shortcode TEXT NOT NULL,"
        "  slide_idx INTEGER NOT NULL, path TEXT NOT NULL)"
    )
    conn.commit()


def _vec_blob(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def index(provider_name: str, provider=None) -> int:
    """Embed all slides with one model and store them; skips items already indexed."""
    provider = provider or get_provider(provider_name)
    items = discover_slides()
    conn = _connect(provider)
    _ensure_schema(conn, provider)
    done = {r[0] for r in conn.execute("SELECT item_id FROM items")}
    todo = [it for it in items if it["item_id"] not in done]
    print(f"[{provider_name}] {len(items)} slides, {len(todo)} to embed -> {provider.db_path.name}")
    if todo:
        vecs = provider.embed_images([it["path"] for it in todo])
        for it, v in zip(todo, vecs):
            conn.execute(
                "INSERT OR REPLACE INTO items VALUES (?,?,?,?,?)",
                (it["item_id"], it["post_id"], it["shortcode"], it["slide_idx"], str(it["path"])),
            )
            conn.execute(
                "INSERT OR REPLACE INTO visual_items(item_id, embedding) VALUES (?,?)",
                (it["item_id"], _vec_blob(v)),
            )
        conn.commit()
    conn.close()
    print(f"[{provider_name}] done: {len(done) + len(todo)} slide vectors")
    return len(done) + len(todo)


# ---------------------------------------------------------------------------
# Retrieval (cross-modal, post-level dedupe)


def retrieve_scored(
    question: str, provider_name: str = "voyage", top_k: int = 20
) -> list[tuple[str, str, float]]:
    """Return top_k (post_id, item_id, cosine_sim) slide hits, post-deduped.

    A post appears at most once (its best slide); ranking order preserved.
    """
    provider = get_provider(provider_name)
    qvec = provider.embed_query(question)
    conn = _connect(provider)
    rows = conn.execute(
        """
        SELECT v.item_id, i.post_id, v.distance
        FROM visual_items v JOIN items i ON i.item_id = v.item_id
        WHERE v.embedding MATCH ? AND k = ?
        ORDER BY v.distance
        """,
        (_vec_blob(qvec), top_k * 4),
    ).fetchall()
    conn.close()
    seen: set[str] = set()
    out: list[tuple[str, str, float]] = []
    for item_id, post_id, dist in rows:
        if post_id in seen:
            continue
        seen.add(post_id)
        out.append((str(post_id), str(item_id), 1.0 - float(dist)))
        if len(out) >= top_k:
            break
    return out


def retrieve(question: str, provider_name: str = "voyage", top_k: int = 10) -> list[str]:
    """Ranked post_ids for eval consumption (kb.eval aliases shortcodes/ids)."""
    return [pid for pid, _iid, _s in retrieve_scored(question, provider_name, top_k)]


# ---------------------------------------------------------------------------
# Gold set — authored from the actual slide contents (lead slide of each post
# inspected) plus per-post analysis text in kb-posts-all.json.

GOLD_SET: list[dict] = [
    # --- single-post, visually grounded -----------------------------------
    {"question_id": "vi001", "question": "Which carousel shows how to turn one photo of a man in a white t-shirt into multiple new camera angles?", "expected_post_ids": ["DYNprnKDdFr"], "mode": "search", "domain_hint": "ai-design", "difficulty": "easy"},
    {"question_id": "vi002", "question": "Which carousel recommends a catalog of the best websites with style filters for general design inspiration?", "expected_post_ids": ["DY04AwpleW6"], "mode": "search", "domain_hint": "inspiration", "difficulty": "easy"},
    {"question_id": "vi003", "question": "Which post shows color palettes with hex codes like 2B0A88 laid over vintage botanical illustrations?", "expected_post_ids": ["DZIFpkJleov"], "mode": "search", "domain_hint": "color", "difficulty": "easy"},
    {"question_id": "vi004", "question": "Which carousel features the website Devouring Details by Rauno Freiberg about interface details and interaction metaphors?", "expected_post_ids": ["DZYEipolXZJ"], "mode": "search", "domain_hint": "inspiration", "difficulty": "medium"},
    {"question_id": "vi005", "question": "Which carousel has a slide titled share your core beliefs as part of a 10 core pillars personal brand framework?", "expected_post_ids": ["DZaUAv_jODe"], "mode": "search", "domain_hint": "branding", "difficulty": "medium"},
    {"question_id": "vi006", "question": "Which post shows a tool called asciinator that turns images into ASCII art?", "expected_post_ids": ["DZj9G-hEiZW"], "mode": "search", "domain_hint": "tools", "difficulty": "easy"},
    {"question_id": "vi007", "question": "Which carousel shows a hand holding a botanical fragrance bottle under giant 'the product' typography?", "expected_post_ids": ["DZxnLlkDaHx"], "mode": "search", "domain_hint": "ai-design", "difficulty": "easy"},
    {"question_id": "vi008", "question": "Which carousel recommends a library of modern web UI patterns and interactions at interfaces.dev?", "expected_post_ids": ["DaK9bi0jVmN"], "mode": "search", "domain_hint": "tools", "difficulty": "medium"},
    {"question_id": "vi009", "question": "Which poster-style slide lists 10 core skills for frontend and UI design with numbered rows?", "expected_post_ids": ["DaNYCILlDgO"], "mode": "search", "domain_hint": "ai-design", "difficulty": "easy"},
    {"question_id": "vi010", "question": "Which carousel shows a tool called Ditther that turns flat visuals into dithered, textured ones?", "expected_post_ids": ["DaNmxb2jYUh"], "mode": "search", "domain_hint": "tools", "difficulty": "easy"},
    {"question_id": "vi011", "question": "Which carousel is about generating hyper-realistic AI images of a woman holding a red cosmetic product?", "expected_post_ids": ["DaQQ79mjeo3"], "mode": "search", "domain_hint": "ai-design", "difficulty": "easy"},
    {"question_id": "vi012", "question": "Which carousel introduces a designer's favorite resources from a few past carousels, on a dark opening slide?", "expected_post_ids": ["DaZ-xbaEuph"], "mode": "search", "domain_hint": "resources", "difficulty": "medium"},
    {"question_id": "vi013", "question": "Which slide titled 'Why Foundations Matter' argues design systems should start with rules, scales, tokens and principles before components?", "expected_post_ids": ["DaiaqXrnxu2"], "mode": "search", "domain_hint": "design-systems", "difficulty": "medium"},
    {"question_id": "vi014", "question": "Which carousel explains why pure black is a bad text color for dark theme UIs and suggests softer dark greys?", "expected_post_ids": ["DaqrQbYjuMa"], "mode": "search", "domain_hint": "color", "difficulty": "easy"},
    {"question_id": "vi015", "question": "Which post has an orange slide recommending recent.design as a clean gallery of current design work for layout inspiration?", "expected_post_ids": ["DbYbGxekWK5"], "mode": "search", "domain_hint": "inspiration", "difficulty": "medium"},
    {"question_id": "vi016", "question": "Which carousel has a slide asking what AI slop actually is, with a 3-step fix for Claude Code web design?", "expected_post_ids": ["DblU1r_HA5p"], "mode": "search", "domain_hint": "ai-design", "difficulty": "easy"},
    {"question_id": "vi017", "question": "Which font-pairing carousel shows a combination of a script font called Tempting with the geometric sans Switzer over a yellow field?", "expected_post_ids": ["Dblrpj-E_Lf"], "mode": "search", "domain_hint": "typography", "difficulty": "hard"},
    {"question_id": "vi018", "question": "Which carousel's first step, 'Steal From the Pros', uses styles.refero.design and a DESIGN.md file so an AI agent copies a whole look?", "expected_post_ids": ["DcNMBB0FgD8"], "mode": "search", "domain_hint": "ai-design", "difficulty": "medium"},
    {"question_id": "vi019", "question": "Which post shows a triptych poster series built around a blue screen of death aesthetic?", "expected_post_ids": ["DcoxWY4lbn-"], "mode": "search", "domain_hint": "graphic-design", "difficulty": "easy"},
    {"question_id": "vi020", "question": "Which carousel lists resources for designers with no development background to build and deploy a portfolio website?", "expected_post_ids": ["DbYbGxekWK5"], "mode": "search", "domain_hint": "career", "difficulty": "medium"},
    {"question_id": "vi021", "question": "Which carousel demonstrates an AI product photography workflow that layers product shots, scene backgrounds, models and props?", "expected_post_ids": ["DZxnLlkDaHx"], "mode": "search", "domain_hint": "ai-design", "difficulty": "hard"},
    {"question_id": "vi022", "question": "Which carousel teaches AI image generation via specific composition, lighting and context instead of generic prompts?", "expected_post_ids": ["DaQQ79mjeo3"], "mode": "search", "domain_hint": "ai-design", "difficulty": "medium"},
    {"question_id": "vi023", "question": "Which carousel presents a personal branding framework with pillars like sharing your origin story and unique language?", "expected_post_ids": ["DZaUAv_jODe"], "mode": "search", "domain_hint": "branding", "difficulty": "medium"},
    {"question_id": "vi024", "question": "Which carousel curates websites for color theory, cognitive bias research and AI-driven design nudges?", "expected_post_ids": ["DZj9G-hEiZW"], "mode": "search", "domain_hint": "resources", "difficulty": "medium"},
    {"question_id": "vi025", "question": "Which carousel is a curated list of design and development tools for UI patterns, diagramming and product inspiration?", "expected_post_ids": ["DaK9bi0jVmN"], "mode": "search", "domain_hint": "tools", "difficulty": "medium"},
    {"question_id": "vi026", "question": "Which post organizes 42 skills into six layers for AI-assisted design and frontend development?", "expected_post_ids": ["DaNYCILlDgO"], "mode": "search", "domain_hint": "ai-design", "difficulty": "medium"},
    {"question_id": "vi027", "question": "Which carousel lists 20 resources including handwritten fonts, rare free fonts and SVG tools?", "expected_post_ids": ["DaZ-xbaEuph"], "mode": "search", "domain_hint": "typography", "difficulty": "medium"},
    # --- multi-post --------------------------------------------------------
    {"question_id": "vi028", "question": "Which carousels are about AI image generation or editing for branding and product shots?", "expected_post_ids": ["DYNprnKDdFr", "DZxnLlkDaHx", "DaQQ79mjeo3"], "mode": "search", "domain_hint": "ai-design", "difficulty": "medium"},
    {"question_id": "vi029", "question": "Which carousels recommend websites or galleries for design inspiration?", "expected_post_ids": ["DY04AwpleW6", "DbYbGxekWK5", "DZYEipolXZJ"], "mode": "search", "domain_hint": "inspiration", "difficulty": "medium"},
    {"question_id": "vi030", "question": "Which carousels describe Claude or AI-agent workflows for producing better web designs?", "expected_post_ids": ["DblU1r_HA5p", "DcNMBB0FgD8", "DaNYCILlDgO"], "mode": "search", "domain_hint": "ai-design", "difficulty": "hard"},
]


def write_gold_set() -> Path:
    GOLD_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(GOLD_PATH, "w", encoding="utf-8") as f:
        json.dump(GOLD_SET, f, indent=2, ensure_ascii=False)
    print(f"gold set written: {GOLD_PATH} ({len(GOLD_SET)} questions)")
    return GOLD_PATH


def load_gold_set() -> list[dict]:
    with open(GOLD_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Spike eval


def _eval_provider(provider_name: str, gold_set: list[dict]) -> dict:
    from kb.eval import run_retrieval_eval

    corpus = _load_corpus()
    result = run_retrieval_eval(
        corpus,
        gold_set,
        retriever_fn=lambda q: retrieve(q, provider_name=provider_name, top_k=10),
    )
    return result


def _clamped_pixels(w: int, h: int) -> int:
    """Voyage-billable pixels for an image: clamped to [50k, 2M]."""
    return min(VOYAGE_MAX_PIXELS_PER_IMAGE, max(VOYAGE_MIN_PIXELS_PER_IMAGE, w * h))


def _slide_pixel_total(paths: list[Path]) -> int:
    """Sum voyage-billable (clamped) pixels over the given slide files."""
    from PIL import Image

    return sum(_clamped_pixels(*Image.open(p).size) for p in paths)


def _cost(provider_name: str, n_images: int, n_calls: int, pixels: int) -> dict:
    if provider_name == "voyage":
        est_usd = pixels / 1e9 * VOYAGE_USD_PER_1B_PIXELS
        per_image = est_usd / n_images if n_images else 0.0
        return {
            "model": PROVIDERS[provider_name].model,
            "images_embedded": n_images,
            "api_requests": n_calls,
            "pixels_billed": pixels,
            "estimated_usd": round(est_usd, 4),
            "notes": (
                "voyage: per-pixel billing, $0.60/1B input px, clamped 50k-2M px "
                f"per image (~${per_image:.6f}/image here); standard tier"
            ),
        }
    est_usd = n_images * GEMINI_USD_PER_IMAGE_BATCH
    return {
        "model": PROVIDERS[provider_name].model,
        "images_embedded": n_images,
        "api_requests": n_calls,
        "images_billed": n_images,
        "estimated_usd": round(est_usd, 4),
        "notes": (
            "gemini: batch/paid-tier image rate ~$0.00006/image "
            "(standard ~2x); this spike ran on the free tier so $0 was actually spent"
        ),
    }



def run_spike() -> dict:
    """Index (if needed) both models, run the gold-set eval, write the report."""
    gold = load_gold_set() if GOLD_PATH.exists() else write_gold_set()
    total_px = _slide_pixel_total([s["path"] for s in discover_slides()])
    report: dict = {
        "spike": "visual-image",
        "models": {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    for name in ("voyage", "gemini"):
        provider = PROVIDERS[name]
        n_vecs = index(name)
        n_calls = -(-n_vecs // provider.batch_size)
        res = _eval_provider(name, gold)
        per_q = res.pop("per_question")
        report["models"][name] = {
            "model": provider.model,
            "dims": provider.dims,
            "slides_indexed": n_vecs,
            "db": str(provider.db_path.relative_to(REPO_ROOT)),
            "metrics": res,
            "cost": _cost(name, n_vecs, n_calls, total_px),
            "per_question": per_q,
        }

    v, g = report["models"]["voyage"]["metrics"], report["models"]["gemini"]["metrics"]
    score_v = v["recall@5"] * 2 + v["ndcg@10"] + v["mrr"]
    score_g = g["recall@5"] * 2 + g["ndcg@10"] + g["mrr"]
    winner = "voyage" if score_v >= score_g else "gemini"
    report["winner"] = winner
    report["verdict"] = (
        f"{winner} wins the image spike "
        f"(R@5 {max(v['recall@5'], g['recall@5']):.3f} vs {min(v['recall@5'], g['recall@5']):.3f}, "
        f"nDCG@10 {max(v['ndcg@10'], g['ndcg@10']):.3f} vs {min(v['ndcg@10'], g['ndcg@10']):.3f}, "
        f"MRR {max(v['mrr'], g['mrr']):.3f} vs {min(v['mrr'], g['mrr']):.3f})"
    )
    print(f"\n=== visual-image spike ===")
    for name, m in report["models"].items():
        mt = m["metrics"]
        print(
            f"{name:7s} ({m['model']}): R@5={mt['recall@5']:.3f} R@10={mt['recall@10']:.3f} "
            f"nDCG@10={mt['ndcg@10']:.3f} MRR={mt['mrr']:.3f} | est cost ${m['cost']['estimated_usd']}"
        )
    print(f"winner: {winner}")
    print(f"verdict: {report['verdict']}")

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RUNS_DIR / f"{ts}-visual-image-spike.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"report written: {out}")
    return report


# ---------------------------------------------------------------------------
# CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index", action="store_true", help="build both slide vector DBs")
    ap.add_argument("--gold", action="store_true", help="write the gold set JSON")
    ap.add_argument("--eval", action="store_true", help="run the spike eval + write report")
    ap.add_argument("--retrieve", metavar="QUESTION", help="sample cross-modal retrieve")
    ap.add_argument("--provider", choices=list(PROVIDERS), default="voyage")
    ap.add_argument("--all", action="store_true", help="index + gold + eval")
    args = ap.parse_args(argv)

    if args.retrieve:
        hits = retrieve_scored(args.retrieve, args.provider, top_k=5)
        for pid, iid, score in hits:
            print(f"{score:.4f}  post={pid}  slide={iid}")
        return 0
    if args.all or args.index:
        for name in PROVIDERS:
            index(name)
    if args.all or args.gold:
        write_gold_set()
    if args.all or args.eval:
        run_spike()
    if not (args.all or args.index or args.gold or args.eval or args.retrieve):
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
