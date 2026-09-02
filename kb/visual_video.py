"""Visual-tier VIDEO spike: voyage-multimodal-3.5 vs gemini-embedding-2.

Head-to-head on text->video retrieval over the uiux corpus video posts.
Each video is sampled to <=32 frames (1 fps up to 32s duration, uniform
sample beyond), every frame is embedded per model, and vectors are stored
in per-model file-backed sqlite-vec DBs keyed (post_id, frame_idx).
Retrieval is POST level: an item hit counts toward its post_id; a post is
retrieved if ANY of its frames ranks in the top-k (deduped to first
occurrence) so metrics are comparable to the text tier.

Shared multimodal provider abstraction (mirrors kb/visual_image.py):

    Provider(name, model, dims,
             embed_images(images: list[PIL.Image]) -> np.ndarray [n, dims],
             embed_query(text: str) -> np.ndarray [dims])

- VoyageMultimodal: voyageai.Client().multimodal_embed(
      inputs=[[img], ...], model='voyage-multimodal-3.5',
      input_type='document'|'query') -> .embeddings[i] is a 1024-dim list.
  Inputs must be List[List[str|PIL.Image]], never bare strings.
- GeminiMultimodal: genai.Client().models.embed_content(
      model='gemini-embedding-2',
      contents=[Part.from_bytes(data=jpeg, mime_type='image/jpeg'), ...])
      -> .embeddings[i].values is a 3072-dim list. Batched per call to
  respect the constrained free-tier embed quota; 429s back off and retry.

NOTE: Gemini video embeddings do NOT process audio — the frame visuals are
the only signal indexed here; transcripts remain the speech-retrieval
surface (handled by the text tier).

DBs: data/kb/visual-video-voyage.db, data/kb/visual-video-gemini.db
     (vec0 virtual table FLOAT[dims]; separate DBs per model, never mixed).
Gold: data/eval/gold-set-visual-video.json (same schema as gold-set-v1.json;
      expected_post_ids use SHORTCODES, aliased to post_id by kb.eval).
Report: data/eval/runs/<ts>-visual-video-spike.json

Usage: uv run python -m kb.visual_video [--smoke] [--index] [--eval] [--all]
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from kb.eval import load_corpus, load_gold_set, run_retrieval_eval

REPO_ROOT = Path(__file__).resolve().parent.parent
MEDIA_ROOT = Path(r"C:/Users/evano/repos/scrape-ig-saved-list/data/uiux")
MANIFEST = MEDIA_ROOT / "uiux_manifest.json"
CORPUS_PATH = REPO_ROOT / "data" / "uiux" / "kb-posts.json"
GOLD_PATH = REPO_ROOT / "data" / "eval" / "gold-set-visual-video.json"
RUNS_DIR = REPO_ROOT / "data" / "eval" / "runs"

VOYAGE_DB = REPO_ROOT / "data" / "kb" / "visual-video-voyage.db"
GEMINI_DB = REPO_ROOT / "data" / "kb" / "visual-video-gemini.db"

MAX_FRAMES = 32
FPS_CAP_SECONDS = 32.0
MAX_VIDEO_SECONDS = 120.0  # Gemini embed cap; longer videos are excluded
FRAME_LONG_SIDE = 640
JPEG_QUALITY = 82
VOYAGE_BATCH = 8
GEMINI_BATCH = 5
GEMINI_RETRIES = 5

# Cost accounting (per docs/visual-tier-spike-plan.md + voyage pricing):
# - voyage-multimodal-3.5: $0.60 per 1 BILLION input pixels
# - gemini-embedding-2:    ~$0.0004 per video frame (batch estimate)
COST = {
    "voyage-multimodal-3.5": {"kind": "pixels", "per_1b_px": 0.60},
    "gemini-embedding-2": {"kind": "frame", "per_frame": 0.0004},
}


# ---------------------------------------------------------------------------
# Media discovery


def discover_videos() -> list[dict]:
    """Return corpus records for every post whose folder has video.mp4."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    corpus = {p["shortcode"]: p for p in load_corpus(CORPUS_PATH)}
    out = []
    for sc, info in manifest.items():
        d = MEDIA_ROOT / info["canonical_dataset"] / info["post_folder"]
        if (d / "video.mp4").exists():
            rec = corpus.get(sc)
            out.append(
                {
                    "shortcode": sc,
                    "post_id": str(rec["post_id"]) if rec else sc,
                    "dir": d,
                    "username": info["username"],
                    "duration": None,
                }
            )
    return out


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def sample_timestamps(duration: float) -> list[float]:
    """1 fps up to FPS_CAP_SECONDS, uniform MAX_FRAMES samples beyond."""
    if duration <= FPS_CAP_SECONDS:
        n = max(1, int(duration))
        return [i / 1.0 for i in range(n)]
    return [duration * (i + 0.5) / MAX_FRAMES for i in range(MAX_FRAMES)]


def extract_frames(video: Path, timestamps: list[float], out_dir: Path) -> list[Path]:
    """Extract scaled JPEG frames at the given timestamps via ffmpeg."""
    paths = []
    for i, ts in enumerate(timestamps):
        p = out_dir / f"frame_{i:02d}.jpg"
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-ss", f"{ts:.3f}", "-i", str(video),
                "-frames:v", "1",
                "-vf", f"scale=w={FRAME_LONG_SIDE}:h={FRAME_LONG_SIDE}:force_original_aspect_ratio=decrease",
                "-q:v", str(max(2, 31 * JPEG_QUALITY // 100)),
                str(p),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        paths.append(p)
    return paths


# ---------------------------------------------------------------------------
# Providers


class VoyageMultimodal:
    name = "voyage-multimodal-3.5"
    dims = 1024

    def __init__(self) -> None:
        import voyageai

        self.client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])

    def _embed(self, inputs: list[list], input_type: str) -> np.ndarray:
        vecs: list[list[float]] = []
        for i in range(0, len(inputs), VOYAGE_BATCH):
            batch = inputs[i : i + VOYAGE_BATCH]
            res = self.client.multimodal_embed(
                inputs=batch, model=self.name, input_type=input_type
            )
            vecs.extend(res.embeddings)
        return np.asarray(vecs, dtype=np.float32)

    def embed_images(self, images: list) -> np.ndarray:
        return self._embed([[img] for img in images], "document")


    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([[text]], "query")[0]

class GeminiMultimodal:
    name = "gemini-embedding-2"
    dims = 3072

    def __init__(self) -> None:
        from google import genai

        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def _embed(self, parts: list) -> np.ndarray:
        vecs: list[list[float]] = []
        for i in range(0, len(parts), GEMINI_BATCH):
            batch = [[p] for p in parts[i : i + GEMINI_BATCH]]
            delay = 5.0
            for attempt in range(GEMINI_RETRIES):
                try:
                    res = self.client.models.embed_content(
                        model=self.name, contents=batch
                    )
                    break
                except Exception as e:  # quota / transient
                    msg = str(e)
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg or attempt < GEMINI_RETRIES - 1:
                        print(f"    gemini retry {attempt + 1}: {msg[:120]}", flush=True)
                        time.sleep(delay)
                        delay = min(delay * 2, 60.0)
                    else:
                        raise
            vecs.extend(e.values for e in res.embeddings)
        return np.asarray(vecs, dtype=np.float32)

    def embed_images(self, images: list) -> np.ndarray:
        from google.genai import types

        parts = []
        for img in images:
            buf = __import__("io").BytesIO()
            img.save(buf, format="JPEG")
            parts.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"))
        return self._embed(parts)

    def embed_query(self, text: str) -> np.ndarray:
        from google.genai import types

        res = self.client.models.embed_content(model=self.name, contents=[text])
        return np.asarray(res.embeddings[0].values, dtype=np.float32)


PROVIDERS = {"voyage": VoyageMultimodal, "gemini": GeminiMultimodal}
DBS = {"voyage": VOYAGE_DB, "gemini": GEMINI_DB}

def open_db(path: Path, dims: int):
    import sqlite3
    import sqlite_vec

    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS frames USING vec0("
        f"  item_key TEXT PRIMARY KEY,"
        f"  post_id TEXT,"
        f"  shortcode TEXT,"
        f"  frame_idx INTEGER,"
        f"  embedding FLOAT[{dims}]"
        f")"
    )
    return conn


def serialize(vec: np.ndarray) -> bytes:
    import struct

    return struct.pack(f"{len(vec)}f", *vec.astype(np.float32))


def index_provider(provider, db_path: Path, videos: list[dict]) -> dict:
    """Index every frame of every (under-cap) video for one provider."""
    conn = open_db(db_path, provider.dims)
    done = {
        r[0]
        for r in conn.execute("SELECT DISTINCT shortcode FROM frames").fetchall()
    }
    stats = {"posts": 0, "frames": 0, "skipped_over_cap": [], "pixels": 0, "bytes_in": 0}
    for v in videos:
        if v["shortcode"] in done:
            print(f"  {v['shortcode']}: already indexed, skip", flush=True)
            stats["posts"] += 1
            conn2 = conn.execute(
                "SELECT COUNT(*) FROM frames WHERE shortcode = ?", (v["shortcode"],)
            )
            stats["frames"] += conn2.fetchone()[0]
            continue
        dur = v["duration"]
        if dur > MAX_VIDEO_SECONDS:
            print(f"  {v['shortcode']}: {dur:.1f}s > {MAX_VIDEO_SECONDS:.0f}s cap, EXCLUDED", flush=True)
            stats["skipped_over_cap"].append(v["shortcode"])
            continue
        ts_list = sample_timestamps(dur)
        with tempfile.TemporaryDirectory() as td:
            frames = extract_frames(v["dir"] / "video.mp4", ts_list, Path(td))
            from PIL import Image

            imgs = [Image.open(f).convert("RGB") for f in frames]
            for im in imgs:
                stats["pixels"] += im.width * im.height
                stats["bytes_in"] += im.size[0] * im.size[1] * 3
            vecs = provider.embed_images(imgs)
        for idx, vec in enumerate(vecs):
            conn.execute(
                "INSERT OR REPLACE INTO frames(item_key, post_id, shortcode, frame_idx, embedding) VALUES (?,?,?,?,?)",
                (
                    f"{v['post_id']}:{idx}",
                    v["post_id"],
                    v["shortcode"],
                    idx,
                    serialize(vec),
                ),
            )
        conn.commit()
        stats["posts"] += 1
        stats["frames"] += len(ts_list)
        print(f"  {v['shortcode']}: {len(ts_list)} frames embedded ({provider.name})", flush=True)
    conn.close()
    return stats


# ---------------------------------------------------------------------------
# Retrieval (post level)


def retrieve_posts(provider, db_path: Path, query: str, top_k: int = 10) -> list[str]:
    """Embed query, cosine-rank frames, dedupe to first post occurrence."""
    import sqlite_vec

    conn = sqlite3_connect(db_path)
    qv = provider.embed_query(query)
    rows = conn.execute(
        """
        SELECT post_id, embedding FROM frames
        """,
    ).fetchall()
    scored = []
    qn = qv / (np.linalg.norm(qv) + 1e-9)
    for post_id, blob in rows:
        v = np.frombuffer(blob, dtype=np.float32)
        if v.size != provider.dims:
            continue
        score = float(qn @ (v / (np.linalg.norm(v) + 1e-9)))
        scored.append((score, post_id))
    conn.close()
    scored.sort(reverse=True)
    seen: set[str] = set()
    out: list[str] = []
    for _, post_id in scored:
        if post_id not in seen:
            seen.add(post_id)
            out.append(post_id)
            if len(out) >= top_k:
                break
    return out


def sqlite3_connect(path: Path):
    import sqlite3
    import sqlite_vec

    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


# ---------------------------------------------------------------------------
# Cost


def cost_for(provider_name: str, stats: dict) -> dict:
    c = COST[provider_name]
    if c["kind"] == "pixels":
        usd = stats["pixels"] / 1e9 * c["per_1b_px"]
        return {"unit": "pixels", "amount": stats["pixels"], "usd": round(usd, 4)}
    usd = stats["frames"] * c["per_frame"]
    return {"unit": "frames", "amount": stats["frames"], "usd": round(usd, 4)}


# ---------------------------------------------------------------------------
# Eval + report


def eval_provider(provider, db_path: Path, gold_set: list[dict]) -> dict:
    corpus = load_corpus(CORPUS_PATH)

    def retriever_fn(question: str):
        return retrieve_posts(provider, db_path, question, top_k=10)

    return run_retrieval_eval(corpus, gold_set, retriever_fn)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    mode = argv[0] if argv else "--all"
    smoke = "--smoke" in argv or mode == "--smoke"

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")

    videos = discover_videos()
    for v in videos:
        v["duration"] = probe_duration(v["dir"] / "video.mp4")
    videos.sort(key=lambda v: v["duration"])
    under_cap = [v for v in videos if v["duration"] <= MAX_VIDEO_SECONDS]
    print(f"video posts: {len(videos)} total, {len(under_cap)} under {MAX_VIDEO_SECONDS:.0f}s cap")

    if smoke:
        v = under_cap[0]
        ts_list = sample_timestamps(v["duration"])[:3]
        with tempfile.TemporaryDirectory() as td:
            frames = extract_frames(v["dir"] / "video.mp4", ts_list, Path(td))
            from PIL import Image

            imgs = [Image.open(f).convert("RGB") for f in frames]
            for prov_name in ("voyage", "gemini"):
                prov = PROVIDERS[prov_name]()
                vecs = prov.embed_images(imgs)
                qv = prov.embed_query("a screen recording showing a design workflow")
                cos = [
                    float(qv @ (vec / (np.linalg.norm(vec) + 1e-9)))
                    for vec in vecs
                ]
                print(f"  {prov.name}: vecs={vecs.shape}, query cos={ [round(c, 3) for c in cos] }")
        return 0

    report: dict = {
        "spike": "visual-video",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "models": [VoyageMultimodal.name, GeminiMultimodal.name],
        "videos_total": len(videos),
        "videos_indexed": len(under_cap),
        "excluded_over_cap": [v["shortcode"] for v in videos if v["duration"] > MAX_VIDEO_SECONDS],
        "note_audio": "Gemini video embeddings do not process audio; frame visuals are the only signal.",
        "gold_set": str(GOLD_PATH.relative_to(REPO_ROOT)),
        "providers": {},
    }

    if mode in ("--all", "--index"):
        for prov_name in ("voyage", "gemini"):
            print(f"[index] {prov_name}", flush=True)
            prov = PROVIDERS[prov_name]()
            stats = index_provider(prov, DBS[prov_name], under_cap)
            stats["cost"] = cost_for(PROVIDERS[prov_name].name, stats)
            report["providers"].setdefault(prov_name, {})["index"] = stats
            print(f"  -> {stats['frames']} frames, cost ${stats['cost']['usd']}", flush=True)

    if mode in ("--all", "--eval"):
        gold = load_gold_set(GOLD_PATH)
        for prov_name in ("voyage", "gemini"):
            prov = PROVIDERS[prov_name]()
            metrics = eval_provider(prov, DBS[prov_name], gold)
            report["providers"].setdefault(prov_name, {})["metrics"] = {
                k: v for k, v in metrics.items() if k != "per_question"
            }
            report["providers"][prov_name]["per_question"] = metrics["per_question"]
            m = metrics
            print(
                f"[eval] {prov.name}: R@5={m['recall@5']:.3f} R@10={m['recall@10']:.3f} "
                f"nDCG@10={m['ndcg@10']:.3f} MRR={m['mrr']:.3f}",
                flush=True,
            )

        def score(p: dict) -> tuple:
            m = p["metrics"]
            return (m["recall@5"], m["ndcg@10"], m["mrr"])

        v_score, g_score = report["providers"]["voyage"]["metrics"], report["providers"]["gemini"]["metrics"]
        winner = (
            "voyage-multimodal-3.5"
            if score({"metrics": v_score}) >= score({"metrics": g_score})
            else "gemini-embedding-2"
        )
        v_cost = report["providers"]["voyage"]["index"]["cost"]["usd"]
        g_cost = report["providers"]["gemini"]["index"]["cost"]["usd"]
        report["winner"] = winner
        report["verdict"] = (
            f"{winner} wins on post-level retrieval (R@5 voyage={v_score['recall@5']:.3f} "
            f"gemini={g_score['recall@5']:.3f}); index cost voyage=${v_cost} gemini=${g_cost}"
        )
        print(f"[verdict] {report['verdict']}")

    if mode in ("--all", "--index", "--eval"):
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out = RUNS_DIR / f"{ts}-visual-video-spike.json"
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"report -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
